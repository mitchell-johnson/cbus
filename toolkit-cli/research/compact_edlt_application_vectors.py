"""Freeze original application observations without importing an editor.

Raw strings and all recorded phases are retained. In particular an original
256-value SceneBucket diagnostic is not truncated into a valid 232-byte input.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path):
    cases = {}; current = None
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        words = line.split('\t')
        if words[0] == 'case':
            key = (words[2], words[1])
            if key in cases: raise ValueError('Duplicate original case')
            current = {'phases': {}, 'observations': [], 'complete': False, 'ended': False}
            cases[key] = current
        elif words[0] in ('runtime', 'runtime-file'): continue
        elif current is None: continue
        elif words[0] == 'pp':
            phase = current['phases'].setdefault(words[1], {})
            # A caught exception can dump the same stage again, as in the
            # original capture. It must not replace a different PP value.
            value = base64.b64decode(words[3], validate=True).decode()
            if words[2] in phase and phase[words[2]] != value:
                raise ValueError('Conflicting repeated PP observation')
            phase[words[2]] = value
        elif words[0] == 'complete': current['complete'] = words[1] == 'true'
        elif words[0] == 'endcase': current['ended'] = True
        else:
            current['observations'].append({'kind': words[0], 'stage': words[1],
                'value': base64.b64decode(words[2], validate=True).decode()})
    return cases


def compact(directory):
    report_path = directory / 'execution-report.json'
    report = json.loads(report_path.read_text())
    plan_path = directory / 'case-plan.json'
    if sha(plan_path) != report['planned_case_sha256']: raise ValueError('Case plan changed')
    plan = {row['id']: row for row in json.loads(plan_path.read_text())['cases']}
    captures = {}; sources = []
    for run in report['runs']:
        folder = directory / run['run']
        if sha(folder / 'NativeEdltApplicationsProbe.cs') != run['source_sha256']:
            raise ValueError('Original probe source changed')
        if sha(folder / 'metadata.json') != run['metadata_sha256']: raise ValueError('Run metadata changed')
        for name, digest in run['input_sha256'].items():
            if sha(folder / name) != digest: raise ValueError('Run input changed: ' + name)
        for capture in run['captures']:
            path = folder / capture['stdout']
            if sha(path) != capture['stdout_sha256']: raise ValueError('Original capture changed')
            if (folder / capture['stdout'].replace('stdout', 'stderr')).read_bytes():
                raise ValueError('Unexpected original stderr')
            result = capture['result']
            if not result['complete'] or result['exit_code'] != 0: raise ValueError('Incomplete original process')
            captures[run['run'], capture['stdout']] = parse(path)
        sources.append(run)
    output = {'format': 'cbus-edlt-application-observations-v1',
        'execution_report_sha256': sha(report_path), 'case_plan_sha256': sha(plan_path),
        'sources': sources, 'vectors': [], 'physical_device_verified': False,
        'full_form_initialization_verified': False, 'expected_values_generated_by_python_editor': False}
    baseline = None; strings = {}; output['observation_values'] = []
    def intern(value):
        if value not in strings:
            strings[value] = len(output['observation_values'])
            output['observation_values'].append(value)
        return strings[value]
    for selected in report['selected_case_provenance']:
        row = captures[selected['run'], selected['capture_file']][selected['mode'], selected['id']]
        if not row['ended'] or any(len(values) != 874 for values in row['phases'].values()):
            raise ValueError('Incomplete original parameter dictionary')
        if row['complete'] != selected['completed']: raise ValueError('Completion mismatch')
        if any(obs['kind'] == 'metadata-request' for obs in row['observations']):
            raise ValueError('Unexpected metadata creation')
        initial = row['phases']['raw-input']
        if baseline is None: baseline = initial; output['baseline'] = initial
        if set(initial) != set(baseline): raise ValueError('Original PP schema changed')
        output['vectors'].append({'case': selected['id'], 'mode': selected['mode'],
            'run': selected['run'], 'capture': selected['capture_file'],
            'input_case': plan[selected['id']], 'complete': row['complete'],
            'initial': {name: value for name, value in initial.items() if value != baseline[name]},
            'phases': {stage: {name: value for name, value in values.items() if value != initial[name]}
                       for stage, values in row['phases'].items()},
            'observations': [[obs['kind'], obs['stage'], intern(obs['value'])] for obs in row['observations']]})
    if len(output['vectors']) != 435: raise ValueError('Expected all 435 selected compositions')
    return output


def compact_terminal(directory):
    """Independent canonical scene/save capture; preserve all original data."""
    path = directory / 'metadata.json'; metadata = json.loads(path.read_text())
    if sha(directory / 'NativeEdltApplicationPhasesProbe.cs') != metadata['source_sha256']:
        raise ValueError('Original source changed')
    if sha(directory / 'verify_edlt_application_phases.py') != metadata['driver_sha256']:
        raise ValueError('Capture driver changed')
    for name, digest in metadata['input_sha256'].items():
        if sha(directory / name) != digest: raise ValueError('Original input changed')
    for name in ('stdout', 'stderr'):
        if sha(directory / (name + '.txt')) != metadata['result'][name + '_sha256']:
            raise ValueError('Original process output changed')
    if not metadata['result']['complete'] or metadata['result']['exit_code'] != 0 or (directory / 'stderr.txt').read_bytes():
        raise ValueError('Original process did not complete cleanly')
    rows = parse(directory / 'stdout.txt'); baseline = None; strings = {}
    result = {'format': 'cbus-edlt-application-terminal-vectors-v1', 'source': metadata,
        'metadata_sha256': sha(path), 'vectors': [], 'observation_values': [],
        'physical_device_verified': False, 'full_form_initialization_verified': False}
    def intern(text):
        if text not in strings:
            strings[text] = len(result['observation_values']); result['observation_values'].append(text)
        return strings[text]
    for case in metadata['cases']:
        row = rows['global', case['id']]
        if not row['ended'] or not row['complete'] or any(len(values) != 874 for values in row['phases'].values()):
            raise ValueError('Original model did not complete')
        if any(o['kind'] in ('metadata-request', 'failure', 'cleanup-failure') for o in row['observations']):
            raise ValueError('Unexpected original failure or metadata creation')
        initial = row['phases']['raw-input']
        if len(initial['SceneBucket'].split()) != 232: raise ValueError('Noncanonical scene fixture')
        if baseline is None: baseline = initial; result['baseline'] = initial
        result['vectors'].append({'case': case['id'], 'mode': 'global', 'input_case': case,
            'initial': {name: value for name, value in initial.items() if value != baseline[name]},
            'phases': {stage: {name: value for name, value in values.items() if value != initial[name]}
                       for stage, values in row['phases'].items()},
            'observations': [[o['kind'], o['stage'], intern(o['value'])] for o in row['observations']]})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path); parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); result = compact(args.directory)
    with args.output.open('x') as target:
        json.dump(result, target, ensure_ascii=True, separators=(',', ':')); target.write('\n')
    print(json.dumps({'vectors': len(result['vectors']), 'sha256': sha(args.output)}))
