"""Promote compact literal original Global Programming vectors, no business model."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cbus_toolkit.unitspec import UnitSpecStore


def main():
    base = ROOT / 'research/runtime/edlt-global-programming'
    inputs = [base / 'matrix-3200bb2992/analysis.json', base / 'order-01988a2acc/analysis.json',
              ROOT / 'research/vendor/unitspec-plain/KEYGL5.xml']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    matrix, reverse = (json.loads(path.read_text()) for path in inputs[:2])
    assert matrix['passed'] and reverse['passed']
    spec = UnitSpecStore(inputs[-1].parent).load(inputs[-1].name)
    keep = ('Name', 'Type', 'Address', 'ArraySize', 'ArraySkip', 'BitAddress', 'BitSize', 'DefaultValue')
    parameters = [{'name': p.name, 'type': p.type, 'fields': {k: v for k, v in p.fields.items() if k in keep}}
                  for p in spec.parameters.values()]
    sources = []
    for context in ('defaults-loaded-fixture', 'retained-lighting-scene-mra'):
        rows = [r for r in matrix['cases'] if r['context'] == context and r['fault'] == 'none']
        first = rows[0]
        assert len(rows) == 16
        for row in rows:
            assert row['input'] == first['input'] and row['afterload'] == first['afterload']
            assert row['saves'][0]['after_original_save'] == first['saves'][0]['after_original_save']
        sources.append({'context': context, 'input': first['input'],
            'after_load_delta': {k: v for k, v in first['afterload'].items() if first['input'][k] != v},
            'after_save_delta': {k: v for k, v in first['saves'][0]['after_original_save'].items() if first['afterload'][k] != v},
            'source_crcs': first['saves'][0]['source_crcs'],
            'parameter_order': first['saves'][0]['pp_attribute_input_order'],
            'masks': [{'mask': row['mask'], 'ordered_payload': list(row['saves'][0]['payload'].items()),
                'original_result': row['saves'][0]['original_return'], 'source_dirty_after': row['saves'][0]['dirty_after']}
                     for row in rows]})
    sequential = next(row for row in matrix['cases'] if row['fault'] == 'sequential')
    document = {'format': 'cbus-edlt-global-original-vectors-v1', 'source_hashes': hashes,
        'probe_sha256': matrix['source_sha256'], 'compiled_probe_sha256': matrix['compiled_probe_sha256'],
        'parameters': parameters, 'sources': sources,
        'reversed_order': [{'mask': row['mask'], 'parameter_order': row['saves'][0]['pp_attribute_input_order'],
            'ordered_payload': list(row['saves'][0]['payload'].items())} for row in reverse['cases']],
        'sequential': [{'ordered_payload': list(save['payload'].items()), 'source_changes': save['source_changes'],
                       'dirty_before': save['dirty_before'], 'dirty_after': save['dirty_after']} for save in sequential['saves']],
        'negative_results': [{'name': row['name'], 'phase_counts': row['phase_counts'],
            'save_calls': [{'original_return': save['original_return'], 'false_complete': save['false_complete'],
                'rejected_parameters': save['rejected_parameters'], 'ordered_payload': list(save['payload'].items())}
                for save in row['saves']]} for row in matrix['cases'] if row['fault'] not in ('none', 'sequential')],
        'scope': {'original_model_category_path': True, 'original_full_form': False,
            'source_project_setter_executed': False, 'physical_device_verified': False}}
    path = ROOT / 'research/fixtures/edlt-global-programming-vectors.json'
    path.write_text(json.dumps(document, indent=2) + '\n')
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[str(p.relative_to(ROOT))] for p in inputs)
    print(path, hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size)


if __name__ == '__main__': main()
