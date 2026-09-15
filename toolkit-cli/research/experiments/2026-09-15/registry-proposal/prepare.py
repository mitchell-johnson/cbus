"""Build static proposal records; does not load original code or access registry."""
from pathlib import Path
import collections
import hashlib
import json
import re
import zipfile

ROOT = Path('/Users/mitchell/source/cbus/toolkit-cli')
BASE = Path('/Volumes/external/cbus-toolkit-agent-runtime/toolkit-update-applicability')
OUT = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def emit(name, value):
    with (OUT / name).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=True) + '\n')


inventory_path = BASE / 'static-v1/inventory.json'
inventory_bytes = inventory_path.read_bytes()
assert digest(inventory_bytes) == '6b1708300f47c617e0dab410eadc6894f8373b4d3ea2ba63729e9f9de47aa7fd'
inventory = json.loads(inventory_bytes)
common = Path(inventory['inputs']['common.il']['path']).read_bytes()
assert digest(common) == inventory['inputs']['common.il']['sha256']
lines = common.decode('utf-8').splitlines(keepends=True)
names = ['Evaluate', 'EvaluateWithNCalc2', 'CallbackDuringEvaluation',
         'CheckClientConditionDataAsArgument', 'EvaluateCondition',
         'EvaluateRegistryKeyExists', 'ReplaceRegistryRootAbbreviations',
         'EvaluateRegistryEntryExists', 'EvaluateRegistryEntryContent',
         'CompareInt', 'ReplaceFirstOccurrence', '.cctor']
selected = [m for m in inventory['methods']
            if m['source'] == 'common.il' and
            (m['method'] in ['ClientConditionChecker::' + n for n in names]
             or m['method'] == 'Condition::.cctor'
             or m['method'].startswith('Condition::get_')
             or m['method'].startswith('Condition::set_'))]
fragments = []
for method in selected:
    text = ''.join(lines[method['first_line']-1:method['last_line']])
    # The historic inventory hashes stripped method text. Keep exact extraction
    # independently hashed and its inclusive historical source line locations.
    method['extracted_sha256'] = digest(text.encode())
    prior = ''.join(lines[max(0, method['first_line']-8):method['first_line']-1])
    numbers = re.findall(r'// method line (\d+)', prior)
    if numbers:
        method['metadata_token'] = '0x%08x' % (0x06000000 + int(numbers[-1]))
    fragments.append('// historical common.il lines %s..%s\n%s' %
                     (method['first_line'], method['last_line'], text))
with (OUT / 'original-registry-methods.il').open('x') as stream:
    stream.write('\n'.join(fragments))

emit('source-graph.json', {
    'format': 'toolkit-update-registry-static-graph-v1',
    'original_execution': False,
    'registry_or_network_access': False,
    'historical_inventory_sha256': digest(inventory_bytes),
    'original_common_il_sha256': digest(common),
    'methods': selected,
    'provider': {
        'method': 'Microsoft.Win32.Registry.GetValue(string,string,object)',
        'view_requested': 'process-default; no explicit RegistryView argument',
        'runtime_bitness_determined_by_this_DLL': False,
        'call_sites': {'key_exists': '0x2980/IL0039',
                       'entry_exists': '0x2aa0/IL005e',
                       'entry_content': '0x2b8c/IL0064'},
        'key_query': {'entry': 'Test', 'default': {'kind': 'int32', 'value': 1}},
        'entry_query_default': {'kind': 'string', 'value':
            '23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe'},
        'windows_missing_key_value_kinds_and_view_behavior': 'pending native admission pilot',
        'separate_registry32_rollout_in_scope': False,
    },
    'lazy_order': [
        'expression short circuit controls callback invocation',
        'successful condition-result cache hit bypasses leaf and provider',
        'key: path -> expansion -> provider -> null test -> comparator',
        'entry: path -> entry -> expansion -> provider -> ToString/sentinel -> comparator',
        'content: path -> entry -> expansion -> provider -> null/sentinel shortcut',
        'present content: second ToString -> lowercase LHS -> RHS null check -> lowercase RHS',
        'integer helper: parse RHS -> empty/sentinel LHS shortcut -> parse LHS -> comparator',
        'cache insertion occurs only after successful leaf return',
    ],
    'string_comparators': {
        '10': 'lowered String.Equals', '11': 'negated lowered String.Equals',
        '12': 'lowered String.CompareTo > 0', '13': 'lowered String.CompareTo >= 0',
        '14': 'lowered String.CompareTo < 0', '15': 'lowered String.CompareTo <= 0',
        '16': 'lowered String.StartsWith(string)', '17': 'lowered String.Contains(string)',
    },
    'integer_comparators': {'10': '==', '11': '!=', '12': '>', '13': '>=', '14': '<', '15': '<='},
    'source_only_review': {
        'reviewer': '/root/pci_impl', 'execution_or_edits': False,
        'result': 'Confirms query/default/order graph and culture-default overloads; printable ASCII alone does not justify ordinal CompareTo.'
    },
})

fixture_path = ROOT / 'research/fixtures/toolkit-update-conditions-vectors.json'
fixture_bytes = fixture_path.read_bytes()
assert digest(fixture_bytes) == '4d17c1cbe37ca9ffd6be69ad4f560c56e3ba278b6f21ac2f25235f4f2e372962'
fixture = json.loads(fixture_bytes)
cases = [r for r in fixture['cases'] if r['kind'] == 'integer']
identifiers = {r['id'] for r in cases}
observations = [r for r in fixture['observations'] if r['id'] in identifiers]
assert len(cases) == len(identifiers) == len(observations) == 107
assert all(r['harness_valid'] for r in observations)
assert collections.Counter('error' if r['error'] else 'bool' for r in observations) == {'bool': 76, 'error': 31}
emit('integer-evidence.json', {
    'format': 'toolkit-update-registry-reused-integer-evidence-v1',
    'source_fixture': str(fixture_path), 'source_fixture_sha256': digest(fixture_bytes),
    'new_original_execution': False, 'case_count': 107,
    'boolean_count': 76, 'original_error_count': 31,
    'initial_batch_overall_failed_expectation_preserved': True,
    'registry_outer_missing_branch_executed_in_these_cases': False,
    'cases': cases, 'observations': observations,
})

SENTINEL = '23021957-xxx-yy-z-27331bfa-adf0-46be-8d44-18b1a831affe'
ERROR = 'SE.DAD.SESU.Common.Validation.ClientConditionException'
plan = []


def case(number, name, what, how, *, key=True, entry='Value', value=None,
         kind=None, right=None, result=None, message=None, abbreviate=False,
         provider_kind=None, provider_value=None, note=''):
    plan.append({
        'id': 'registry-%02d-%s' % (number, name),
        'original_calls': 1,
        'leaf': {3: 'EvaluateRegistryKeyExists', 4: 'EvaluateRegistryEntryExists',
                 5: 'EvaluateRegistryEntryContent', 6: 'EvaluateRegistryEntryContent'}[what],
        'fixture': {'subkey': 'c%02d' % number, 'key_exists': key,
                    'entry': entry, 'value_kind': kind, 'value': value},
        'condition': {'name': 'R%02d' % number, 'whatToCheck': what, 'howToCheck': how,
                      'fileOrRegistryKeyPath': ('HKCU' if abbreviate else 'HKEY_CURRENT_USER') +
                                              '\\Software\\{owned_root_name}\\c%02d' % number,
                      'registryEntryNameOrProductCode': entry,
                      'comparisonRightSideValue': right},
        'expected_provider_witness': {'kind': provider_kind, 'value': provider_value,
                                      'status': 'prewritten hypothesis, not yet observed'},
        'expected_original': ({'result': result, 'error': None} if message is None else
                              {'result': None, 'error_type': ERROR, 'message': message}),
        'note': note,
    })

case(1, 'existing-key-default', 3, 1, entry='Test', result=True,
     provider_kind='System.Int32', provider_value=1, abbreviate=True,
     note='Present key, absent Test entry; boxed default1 makes key existence true.')
case(2, 'missing-key-negated', 3, 2, key=False, entry='Test', result=True,
     provider_kind='null', note='Missing key returns null; negate existence.')
case(3, 'key-invalid-how-after-read', 3, 0, entry='Test',
     provider_kind='System.Int32', provider_value=1,
     message="error when evaluating condition 'R03': registry keys can only be checked against existence or not-existence, but not against 0",
     note='Getter precedes invalid-how error in exact IL; witness is a separate read.')
case(4, 'missing-entry', 4, 1, result=False, provider_kind='System.String', provider_value=SENTINEL)
case(5, 'literal-sentinel-entry', 4, 1, kind='REG_SZ', value=SENTINEL, result=False,
     provider_kind='System.String', provider_value=SENTINEL, abbreviate=True,
     note='A present literal sentinel is indistinguishable from missing entry to original leaf.')
case(6, 'empty-present-entry', 4, 1, kind='REG_SZ', value='', result=True,
     provider_kind='System.String', provider_value='')
case(7, 'string-lower-equality', 5, 10, kind='REG_SZ', value='MiXeD', right='mIxEd', result=True,
     provider_kind='System.String', provider_value='MiXeD')
case(8, 'string-letter-order', 5, 12, kind='REG_SZ', value='Z', right='a', result=True,
     provider_kind='System.String', provider_value='Z',
     note='One invariant letter comparison only; no punctuation/general collation proof.')
case(9, 'dword-signed-int32', 6, 10, kind='REG_DWORD', value=2147483648,
     right='-2147483648', result=True, provider_kind='System.Int32', provider_value=-2147483648,
     note='Fixture writes raw DWORD80000000; CLR signedness is a hypothesis to verify.')
case(10, 'missing-content-null-rhs', 6, 11, right=None, result=True,
     provider_kind='System.String', provider_value=SENTINEL,
     note='Missing entry bypasses RHS validation/CompareInt and returns true for not-equal.')
case(11, 'empty-content-valid-rhs', 6, 11, kind='REG_SZ', value='', right='0', result=False,
     provider_kind='System.String', provider_value='',
     note='Present empty value enters CompareInt; valid RHS then absent LHS returns false.')
case(12, 'rhs-error-before-invalid-lhs', 6, 10, kind='REG_SZ', value='INVALID', right='BAD-RHS',
     provider_kind='System.String', provider_value='INVALID',
     message='value defined for integer comparison cannot be converted to int: bad-rhs',
     note='Provider and lowercasing precede CompareInt RHS error; invalid LHS not parsed.')
assert len(plan) == 12 and sum(r['original_calls'] for r in plan) == 12
assert sum(r['expected_original'].get('error_type') is not None for r in plan) == 2
emit('pilot-cases.json', {
    'format': 'toolkit-update-registry-original-admission-plan-v1',
    'status': 'proposal_only_not_executed',
    'expectations_prepared_before_original_execution': True,
    'original_call_count': 12, 'provider_witness_call_maximum': 12,
    'other_original_leaf_or_public_Evaluate_entry_calls': 0,
    'culture': 'InvariantCulture', 'process_architecture': 'x86',
    'root_placeholder': 'single new task-owned child of existing HKCU Software; literal frozen before execution',
    'registry_original_operations': 'read only, one GetValue in each unchanged leaf call',
    'fixture_operations': 'owned scratch root/known subkeys/known values only',
    'cases': plan,
    'not_covered': ['all operators', 'general string collation', 'malformed hive/path handling',
                    'registry views other than this process default', 'provider errors/permissions',
                    'REG_EXPAND_SZ or other CLR types', 'expression-to-registry composition',
                    'actual machine applicability'],
})

inputs = [inventory_path, fixture_path,
          Path(inventory['inputs']['common.il']['path']),
          BASE / 'static-v1/selected-methods.il',
          BASE / 'stage-a-extension-v1/cases.json',
          BASE / 'stage-a-extension-v1/original-v1/report.json',
          BASE / 'stage-a-consolidated-v1/analysis.json']
inputs += [Path(v['path']) for k, v in inventory['inputs'].items()
           if k.startswith('assemblies/')]
input_records = {}
for path in inputs:
    data = path.read_bytes()
    input_records[str(path)] = {'bytes': len(data), 'sha256': digest(data)}
for key, item in inventory['inputs'].items():
    if key.startswith('assemblies/'):
        assert input_records[item['path']]['sha256'] == item['sha256']
emit('STATE.json', {
    'status': 'static proposal complete; parent approval and source-reviewed harness required before execution',
    'original_methods_executed_this_task': 0,
    'registry_network_vm_shared_service_calls': False,
    'production_changes': False,
    'historical_inputs': input_records,
    'conditions_v1_acceptance': {
        'path': str(ROOT / 'research/fixtures/toolkit-update-conditions-acceptance.json'),
        'sha256': digest((ROOT / 'research/fixtures/toolkit-update-conditions-acceptance.json').read_bytes()),
        'tests_each_python': 61,
        'published_docs_recorded_separately_from_preexecution_source': True,
    },
})
files = [p for p in sorted(OUT.iterdir()) if p.is_file()]
manifest = {p.name: {'bytes': p.stat().st_size, 'sha256': digest(p.read_bytes())} for p in files}
emit('manifest.json', {'files': manifest, 'original_execution': False})
with zipfile.ZipFile(OUT / 'proposal-evidence.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
    for path in files + [OUT / 'manifest.json']:
        archive.write(path, path.name)
with zipfile.ZipFile(OUT / 'proposal-evidence.zip') as archive:
    for name, item in manifest.items():
        assert digest(archive.read(name)) == item['sha256']
print(json.dumps({'path': str(OUT), 'files': len(manifest),
                  'proposal_sha256': manifest['PROPOSAL.md']['sha256'],
                  'plan_sha256': manifest['pilot-cases.json']['sha256'],
                  'archive_sha256': digest((OUT/'proposal-evidence.zip').read_bytes())}, indent=2))
