"""Explicit combined scheduling/native/CLI acceptance; no full-suite claim."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
import time
import unittest

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from research.acceptance import input_files

MODULES = ['tests.test_thermostat_schedule_levels', 'tests.test_native_thermostat_schedule',
           'tests.test_cli_thermostat_schedule', 'tests.test_cli_thermostat_schedule_dispatch',
           'tests.test_native_thermostat_schedule_integration', 'tests.test_cli_json_output',
           'tests.test_cgate_cleanup']
output = Path(sys.argv[1])
if output.exists():
    raise FileExistsError(output)
paths = input_files('test*thermostat_schedule*.py')
paths.update(ROOT / (name.replace('.', '/') + '.py') for name in MODULES)
paths.add(Path(__file__).resolve())
paths.add(Path(sys.executable).resolve())
for module in tuple(sys.modules.values()):
    location = getattr(module, '__file__', None)
    if location and Path(location).suffix == '.py' and Path(location).resolve().is_relative_to(ROOT):
        paths.add(Path(location).resolve())
for variable in ('CBUS_CGATE_JAVA', 'CBUS_LOCAL_CGATE_VENDOR'):
    if not os.environ.get(variable):
        raise ValueError('Explicit owned native runtime/vendor required')
java = Path(os.environ['CBUS_CGATE_JAVA']).resolve()
paths.add(java)
paths.update([java.parent / 'keytool', java.parent.parent / 'lib/modules', java.parent.parent / 'lib/server/libjvm.dylib', java.parent.parent / 'release'])
paths.update(Path(os.environ['CBUS_LOCAL_CGATE_VENDOR']).resolve().joinpath('lib').rglob('*.jar'))
paths.add(Path(os.environ['CBUS_LOCAL_CGATE_VENDOR']).resolve() / 'cgate.jar')
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
before = {str(path.resolve()): digest(path) for path in sorted(paths)}
manifest = json.loads((Path(__file__).parent / 'inputs-before.json').read_text())
if any(manifest.get(path) != digest for path, digest in before.items()):
    raise ValueError('Run inputs differ from pre-execution archive')
loader = unittest.TestLoader()
suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in MODULES)
if suite.countTestCases() != 67:
    raise ValueError('Expected exactly67 explicitly selected tests')
started = datetime.now(timezone.utc).isoformat()
start = time.monotonic()
result = unittest.TextTestRunner(verbosity=2).run(suite)
after = {path: digest(Path(path)) for path in before}
loaded = {}
validation_errors = []
for name, module in sorted(sys.modules.items()):
    location = getattr(module, '__file__', None)
    if location and Path(location).suffix == '.py':
        location = Path(location).resolve()
        if location.is_relative_to(ROOT):
            loaded[name] = {'path': str(location), 'sha256': digest(location)}
            if before.get(str(location)) != digest(location):
                validation_errors.append('Loaded module outside archived inputs: ' + name)
native_path = Path(os.environ['CBUS_THERMOSTAT_SCHEDULE_EVIDENCE'])
native = json.loads(native_path.read_text())
passed = bool(result.wasSuccessful() and not result.skipped and before == after and not validation_errors
              and native['cleanup_passed'] and not native['network_connections']
              and native['service']['process_exit_confirmed'] and native['service']['work_removed'])
report = {'format': 'thermostat-schedule-combined-acceptance-v1', 'passed': passed,
          'started_at': started, 'elapsed_seconds': time.monotonic() - start,
          'python': sys.version, 'interpreter': str(Path(sys.executable).resolve()),
          'validation_errors': validation_errors, 'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
          'skips': len(result.skipped), 'modules': MODULES, 'input_sha256': before,
          'input_sha256_after': after, 'loaded_modules': loaded,
          'native_evidence_path': str(native_path), 'native_evidence_sha256': digest(native_path),
          'fresh_original_instruction_executions': 0, 'original_captured_cases_replayed': 14,
          'native_test_methods': 5, 'native_project_group_scenarios': 8,
          'physical_device_parity': False, 'whole_suite_acceptance': False,
          'failed_tests': [{'test': test.id(), 'traceback': trace} for test, trace in result.failures + result.errors]}
with output.open('x') as stream:
    json.dump(report, stream, indent=2)
    stream.write('\n')
print(json.dumps({k: report[k] for k in ('passed', 'tests_run', 'failures', 'errors', 'skips')}))
sys.exit(0 if passed else 1)
