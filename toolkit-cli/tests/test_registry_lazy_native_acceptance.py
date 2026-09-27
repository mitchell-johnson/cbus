"""Compare bounded live-wrapper behavior with the pinned original Windows rows.

Python observers below are deterministic doubles; the fixture holds separately
captured original Framework results. This test does not rerun Windows.
"""
import hashlib
import json
from pathlib import Path

import pytest

from cbus_toolkit.toolkit_live_update_conditions import ToolkitLiveUpdateConditions

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/experiments/2026-09-28/registry-lazy-culture-native.json'
NATIVE = json.loads(FIXTURE.read_text())
ROWS = {row['id']: row for row in NATIVE['native_rows']}
PATH = r'HKEY_CURRENT_USER\Software\CbusCliOwnedSynthetic'


class SequenceObserver:
    def __init__(self, *values):
        self.values = iter(values)
        self.queries = []
        self.closed = 0

    def read(self, query):
        self.queries.append(query)
        value = next(self.values)
        return {'kind': 'System.Int32' if type(value) is int else 'System.String', 'value': value}

    def close(self):
        self.closed += 1


def condition(*, what=6, right='0', path=PATH):
    return {'whatToCheck': what, 'howToCheck': 10, 'comparisonRightSideValue': right,
            'fileOrRegistryKeyPath': path, 'registryEntryNameOrProductCode': 'Value'}


def evaluate(expression, conditions, observer, culture='invariant-ascii'):
    report = ToolkitLiveUpdateConditions(observer).evaluate(
        json.dumps({'expression': expression, 'conditions': conditions}).encode(),
        file_context=json.dumps({'format': 'cbus-toolkit-condition-context-v1',
                                 'culture': culture, 'files': []}).encode())
    assert observer.closed == 1
    return report.as_dict()


def test_original_receipt_runtime_source_and_scope_are_bound():
    assert NATIVE['runtime']['mscorlib_sha256'] == '93d46bdac1664dba87641925572c789d71a21bb01dc7c7e5aa99c0eca8335e5e'
    assert NATIVE['vendor_sha256']['SE.DAD.SESU.Common'] == '477fb88de310852611f26d1f845da23b8f0e6b602de8ab61a3eefc06339dc4ba'
    for name in ('CbusLazyRegistryProbe.cs', 'cbus-lazy-run.ps1'):
        assert hashlib.sha256((FIXTURE.parent / name).read_bytes()).hexdigest() == NATIVE['artifacts'][name]
    assert len(ROWS) == 11
    assert NATIVE['cleanup']['fixture_created_new'] and NATIVE['cleanup']['fixture_removed']
    assert NATIVE['cleanup']['owned_processes_remaining'] == 0
    assert not NATIVE['scope']['interactive_user_parity']
    assert not NATIVE['scope']['provider_call_count_instrumented']


@pytest.mark.parametrize('value,native_id', [(0, 'public-first-true'), (1, 'public-fresh-evaluate-false')])
def test_fresh_evaluations_match_original_cache_reset(value, native_id):
    observer = SequenceObserver(value)
    result = evaluate('A and A', {'A': condition()}, observer)
    assert result['evaluation_completed']
    assert result['condition_result'] is ROWS[native_id]['result']
    assert result['condition_result_cache'] == ROWS[native_id]['cache']
    assert len(observer.queries) == 1


def test_true_and_false_caches_are_per_name_not_per_registry_query():
    observer = SequenceObserver(0, 1, 0)
    result = evaluate('A and A and (B or B)', {'A': condition(), 'B': condition()}, observer)
    assert result['condition_result'] is ROWS['callback-b-cached-false']['result']
    assert result['condition_result_cache'] == ROWS['callback-b-cached-false']['cache']
    assert observer.queries[0] == observer.queries[1]
    assert len(observer.queries) == 2
    assert [event['resolution'] for event in result['events']] == ['leaf', 'cached', 'leaf', 'cached']


def test_failed_leaf_is_not_cached_and_a_fresh_corrected_evaluation_succeeds():
    failed = evaluate('A', {'A': condition(right='not-an-int')}, SequenceObserver(0))
    assert not failed['evaluation_completed']
    assert failed['condition_result_cache'] == ROWS['callback-failure-no-cache']['cache'] == {}
    assert failed['condition_result'] is ROWS['callback-failure-no-cache']['result'] is None
    repaired = evaluate('A', {'A': condition()}, SequenceObserver(0))
    assert repaired['condition_result'] is ROWS['callback-repair-retry-true']['result']
    # The original callback was retried inside one checker. The public Python
    # wrapper intentionally requires a fresh observer after any evaluation.


def test_original_short_circuit_preserves_invalid_unvisited_definition():
    observer = SequenceObserver(1)
    result = evaluate('A and B', {'A': condition(), 'B': condition(path='')}, observer)
    assert result['condition_result'] is ROWS['public-short-circuit-false']['result']
    assert result['condition_result_cache'] == ROWS['public-short-circuit-false']['cache']
    assert len(observer.queries) == 1


def test_turkish_counterexample_keeps_culture_domain_explicit():
    assert ROWS['invariant-I-equals-i']['result'] is True
    assert ROWS['turkish-I-not-equal-i']['result'] is False
    result = evaluate('A', {'A': condition(what=5, right='i')}, SequenceObserver('I'))
    assert result['condition_result'] is ROWS['invariant-I-equals-i']['result']
    observer = SequenceObserver('I')
    rejected = evaluate('A', {'A': condition(what=5, right='i')}, observer, culture='tr-TR')
    assert not rejected['evaluation_completed']
    assert rejected['condition_result'] is None
    assert observer.queries == []
