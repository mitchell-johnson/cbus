"""The committed skip census and native release-gate selection stay exact."""
import ast
import json
import unittest

from research import skip_census


class SkipCensusTests(unittest.TestCase):
    def test_committed_census_is_current_and_native_selection_complete(self):
        manifest = json.loads(skip_census.NATIVE_MANIFEST.read_text())
        census, required, errors = skip_census.build(manifest["tests"])
        self.assertEqual(errors, [])
        self.assertEqual(skip_census.CENSUS_PATH.read_text(), skip_census.render(census))
        self.assertTrue(required)
        self.assertEqual(census["summary"]["test_modules"], len(list(skip_census.TESTS.glob("test_*.py"))))

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


if __name__ == "__main__":
    unittest.main()
