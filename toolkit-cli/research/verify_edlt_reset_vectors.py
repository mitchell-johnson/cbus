"""Compact the explicit owned Reset transcripts without importing Python Reset."""
from pathlib import Path
import argparse
import hashlib
import json


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def phases(path):
    result = {}; flags = {}
    for line in path.read_text().splitlines():
        if line.startswith('pp:'):
            key, value, dirty = line.split('\t'); _, stage, name = key.split(':', 2)
            target = result.setdefault(stage, {})
            if name in target: raise ValueError('Duplicate original PP field')
            target[name] = (value, dirty == 'dirty=True')
        elif line.startswith('flag:'):
            _, stage, value = line.split(':', 2); flags[stage] = value == 'True'
    if not all(len(values) == 874 for values in result.values()): raise ValueError('Incomplete original phase')
    return result, flags


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('input_root', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    if args.output.exists(): raise ValueError('Preserve existing evidence; choose a new output')
    baseline = None; records = []; manifests = []
    for folder in ('reset-matrix-v1', 'reset-edges-v1', 'reset-navigation-trace-v1'):
        path = args.input_root / folder; report = json.loads((path / 'report.json').read_text())
        assert report['completed_matrix'] and report['source_unchanged']
        cases = {row['name']: row for row in report['selected_cases']}
        source_name = {'reset-matrix-v1': 'NativeEdltResetMatrixProbe.cs',
                       'reset-edges-v1': 'NativeEdltResetEdgesProbe.cs',
                       'reset-navigation-trace-v1': 'NativeEdltResetNavigationTrace.cs'}[folder]
        assert digest(root / 'research' / source_name) == report['source_before']['probe.cs']
        manifests.append({'folder': folder, 'report_sha256': digest(path / 'report.json'),
            'source': source_name, 'source_sha256': report['source_before']['probe.cs'],
            'compiled_executable_sha256': report['compiled_executable_sha256'],
            'input_source_hashes': report['source_before'], 'windows_provenance': report['provenance'],
            'vendor_manifest': report['vendor_manifest']})
        for row in report['executions']:
            source = path / (row['name'] + '.stdout'); assert digest(source) == row['stdout_sha256']
            values, flags = phases(source)
            raw = {name: value[0] for name, value in values['input'].items()}
            if baseline is None: baseline = raw
            stages = {}; previous = raw
            for stage, state in values.items():
                new = {name: value[0] for name, value in state.items()}
                stages[stage] = {'raw_changes': {k: v for k, v in new.items() if v != previous[k]},
                    'dirty_parameters': [k for k, v in state.items() if v[1]], 'initializing': flags[stage]}
                previous = new
            details = cases[row['case']]
            records.append({'name': folder + '/' + row['name'],
                'source_changes': {k: v for k, v in raw.items() if v != baseline[k]},
                'active_tab': {'tpWidgetFunctions': 'widgets', 'tpGeneralOptions': 'general',
                    'tpStandbyPage': 'standby', 'tpColourOptions': 'colour'}[details['tab']],
                'binding_variant': 'base-c3' if row['wiring'] == 'base' else 'audited-local-wiring',
                'arm': row['arm'], 'metadata_mode': details.get('cache', 'complete'),
                'phases': stages, 'job_id': row['job_id'], 'stdout_sha256': row['stdout_sha256'],
                'stderr_sha256': row['stderr_sha256'], 'input_sha256': row['input_sha256']})
    output = {'format': 'cbus-edlt-reset-windows-vectors-v1', 'baseline': baseline, 'cases': records,
        'sources': manifests, 'compactor_sha256': digest(Path(__file__)),
        'original_execution_count': len(records), 'all_parameter_phase_count': sum(len(r['phases']) for r in records),
        'physical_device_verified': False, 'full_form_verified': False, 'renderer_verified': False,
        'historical_failed_pilots_preserved': ['model-pilot-v1 malformed default', 'handler-pilot-v1 watchdog before Reset']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({'cases': len(records), 'phases': output['all_parameter_phase_count'], 'sha256': digest(args.output)}))


if __name__ == '__main__': main()
