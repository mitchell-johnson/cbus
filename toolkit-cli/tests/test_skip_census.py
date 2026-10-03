"""The committed skip census and native release-gate selection stay exact."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research import skip_census


class SkipCensusTests(unittest.TestCase):
    def test_committed_census_is_current_and_native_selection_complete(self):
        manifest = json.loads(skip_census.NATIVE_MANIFEST.read_text())
        census, required, errors = skip_census.build(manifest["tests"])
        self.assertEqual(errors, [])
        self.assertEqual(skip_census.CENSUS_PATH.read_text(), skip_census.render(census))
        self.assertTrue(required)
        self.assertEqual(census["summary"]["test_modules"], len(skip_census.test_modules()))

    def test_interpreter_evaluates_gates_under_the_native_profile(self):
        source = (
            "import os\n"
            "HOST = os.environ.get('CBUS_CGATE_TEST_HOST')\n"
            "def backend():\n"
            "    if os.environ.get('CBUS_NATIVE_SERVICE_BACKEND') == 'local':\n"
            "        return 'local' if os.environ.get('CBUS_LOCAL_CGATE_VENDOR') else None\n"
            "    return None\n")
        module = skip_census.ModuleInfo("tests/test_synthetic.py", ast.parse(source))
        skip_census._bind(module)
        native = skip_census.Interpreter(module, skip_census.NATIVE_ENVIRONMENT)
        offline = skip_census.Interpreter(module, {})
        cases = {
            "HOST and os.environ.get('CBUS_UNITSPEC_DIR')": (True, False),
            "backend() and os.name == 'posix'": (True, False),
            "all(os.environ.get(k) for k in ('CBUS_CGATE_JAVA', 'CBUS_TOOLKIT_EXE'))": (False, False),
            "os.environ.get('CBUS_SCENE_NATIVE') == '1'": (True, False),
            "Path('/private/vendor/app').is_dir()": (False, False),
        }
        for expression, (expected_native, expected_offline) in cases.items():
            with self.subTest(expression=expression):
                node = ast.parse(expression, mode="eval").body
                self.assertIs(skip_census._truth(native.evaluate(node)), expected_native)
                self.assertIs(skip_census._truth(offline.evaluate(node)), expected_offline)
        unknown = ast.parse("os.access(path, os.X_OK)", mode="eval").body
        self.assertIsNone(skip_census._truth(native.evaluate(unknown)))

    def test_body_skip_calls_carry_their_guarding_condition(self):
        source = (
            "import os, unittest\n"
            "class Native(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        if not os.environ.get('CBUS_TOOLKIT_EXE'):\n"
            "            self.skipTest('original Toolkit')\n"
            "    def test_one(self):\n"
            "        try:\n"
            "            pass\n"
            "        except OSError:\n"
            "            self.skipTest('runtime')\n")
        tree = ast.parse(source)
        cls = tree.body[1]
        sites = skip_census._body_sites(cls.body[0], "scope", "setUp")
        self.assertEqual(len(sites), 1)
        self.assertEqual(ast.unparse(sites[0].condition), "not os.environ.get('CBUS_TOOLKIT_EXE')")
        runtime = skip_census._body_sites(cls.body[1], "scope", "body")
        self.assertEqual([site.kind for site in runtime], ["body.runtime"])


    def test_nested_discovery_and_fixture_scope_do_not_hide_source_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "tests" / "nested"
            folder.mkdir(parents=True)
            (root / "tests/test_top.py").write_text("def test_top(): pass\n")
            path = folder / "test_mixed.py"
            path.write_text("import os, pytest\n"
                "@pytest.fixture(scope='module')\n"
                "def installed_target():\n"
                "    declared = os.environ.get('CBUS_OFFLINE_INSTALLED_TARGET')\n"
                "    if declared is None:\n"
                "        pytest.skip('fresh wheel required')\n"
                "    return declared\n"
                "def test_source(): pass\n"
                "def test_installed(installed_target): pass\n")
            with patch.object(skip_census, "ROOT", root), patch.object(skip_census, "TESTS", root / "tests"), \
                    patch.object(skip_census, "_MODULES", {}):
                self.assertEqual([p.relative_to(root).as_posix() for p in skip_census.test_modules()],
                                 ["tests/nested/test_mixed.py", "tests/test_top.py"])
                module, nodes, _ = skip_census.analyse_module(path)
                self.assertEqual(nodes["tests/nested/test_mixed.py::test_source"], [])
                site, = nodes["tests/nested/test_mixed.py::test_installed"]
                self.assertEqual(skip_census._outcome(module, site, {}), "skips")
                self.assertEqual(skip_census._outcome(module, site,
                    {"CBUS_OFFLINE_INSTALLED_TARGET": skip_census.PROVIDED}), "runs")
                self.assertEqual(skip_census._references(module, site),
                    ({"CBUS_OFFLINE_INSTALLED_TARGET"}, {"installed_wheel"}))
                census, required, _ = skip_census.build([])
                self.assertEqual(census["summary"]["test_modules"], 2)
                self.assertEqual(required, [])
                self.assertEqual(census["modules"]["tests/nested/test_mixed.py"]["gated_tests"], 1)

    def test_nested_imported_fixture_dependency_keeps_its_defining_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "tests" / "nested"
            folder.mkdir(parents=True)
            (folder / "test_shared.py").write_text("import os, pytest\n"
                "GATE = os.environ.get('CBUS_OFFLINE_INSTALLED_TARGET')\n"
                "@pytest.fixture\n"
                "def artifact():\n"
                "    if not GATE: pytest.skip('installed only')\n"
                "@pytest.fixture\n"
                "def chained(artifact): return artifact\n"
                "@pytest.fixture(autouse=True)\n"
                "def boot():\n"
                "    if not GATE: pytest.skip('installed autouse')\n")
            path = folder / "test_consumer.py"
            path.write_text("import pytest\nfrom test_shared import artifact, chained\n"
                            "@pytest.mark.usefixtures('chained')\n"
                            "def test_declared(): pass\n"
                            "def test_source(): pass\n")
            with patch.object(skip_census, "ROOT", root), patch.object(skip_census, "TESTS", root / "tests"), \
                    patch.object(skip_census, "_MODULES", {}):
                _, nodes, _ = skip_census.analyse_module(path)
                site, = nodes["tests/nested/test_consumer.py::test_declared"]
                self.assertEqual(site.owner.path, "tests/nested/test_shared.py")
                self.assertEqual(skip_census._outcome(site.owner, site, {}), "skips")
                self.assertEqual(nodes["tests/nested/test_consumer.py::test_source"], [])
                # Imported dependencies bind against the consumer's own override.
                shadow = folder / "test_shadow.py"
                shadow.write_text("import pytest\nfrom test_shared import chained\n"
                    "@pytest.fixture\n"
                    "def artifact(): return 'consumer-local'\n"
                    "def test_source(chained): pass\n")
                _, shadow_nodes, _ = skip_census.analyse_module(shadow)
                self.assertEqual(shadow_nodes["tests/nested/test_shadow.py::test_source"], [])
                # Importing an autouse fixture exposes its gate even without an argument.
                automatic = folder / "test_autouse.py"
                automatic.write_text("from test_shared import boot as imported_boot\n"
                                     "def test_source(): pass\n")
                _, automatic_nodes, _ = skip_census.analyse_module(automatic)
                autouse_site, = automatic_nodes["tests/nested/test_autouse.py::test_source"]
                self.assertEqual(autouse_site.owner.path, "tests/nested/test_shared.py")
                self.assertEqual(skip_census._outcome(autouse_site.owner, autouse_site, {}), "skips")


    def test_installed_target_never_becomes_a_native_or_hardware_provision(self):
        self.assertNotIn("installed_wheel", skip_census.NATIVE_CATEGORIES)
        for name in ("CBUS_OFFLINE_INSTALLED_TARGET", "CBUS_OFFLINE_INSTALLED_CONSOLE"):
            with self.subTest(name=name):
                self.assertEqual(skip_census.env_category(name), "installed_wheel")
                self.assertNotIn(name, skip_census.NATIVE_ENVIRONMENT)



    def test_direct_parameter_does_not_borrow_a_fixture_skip_but_indirect_does(self):
        source = "import os, pytest\n" \
                 "@pytest.fixture(autouse=True)\n" \
                 "def artifact():\n" \
                 "    if not os.environ.get('CBUS_OFFLINE_INSTALLED_TARGET'): pytest.skip('target required')\n" \
                 "@pytest.mark.parametrize('artifact', [None])\n" \
                 "def test_direct(artifact): pass\n" \
                 "@pytest.mark.parametrize('artifact', [None], indirect=True)\n" \
                 "def test_indirect(artifact): pass\n"
        module = skip_census.ModuleInfo("tests/test_synthetic.py", ast.parse(source))
        skip_census._bind(module)
        self.assertEqual(skip_census._fixture_sites(module, module.functions['test_direct']), [])
        self.assertEqual(len(skip_census._fixture_sites(module, module.functions['test_indirect'])), 1)

    def test_autouse_fixture_gate_reaches_source_body_and_dependency_cycle_terminates(self):
        source = "import os, pytest\n" \
                 "@pytest.fixture(autouse=True)\n" \
                 "def guard(shared):\n" \
                 "    if not os.environ.get('CBUS_OFFLINE_INSTALLED_TARGET'): pytest.skip('target required')\n" \
                 "@pytest.fixture\n" \
                 "def shared(guard): return guard\n" \
                 "def test_source(): pass\n"
        module = skip_census.ModuleInfo("tests/test_synthetic.py", ast.parse(source))
        skip_census._bind(module)
        sites = skip_census._fixture_sites(module, module.functions['test_source'])
        self.assertEqual(len(sites), 1)
        self.assertEqual(skip_census._outcome(module, sites[0], {}), 'skips')


if __name__ == "__main__":
    unittest.main()
