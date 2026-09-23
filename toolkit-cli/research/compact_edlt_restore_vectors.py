"""Compact independently captured Windows outputs; no Python editor is invoked."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path


def digest(raw): return hashlib.sha256(raw).hexdigest()


def parse(raw):
    phases, controls = {}, {}
    for line in raw.decode('utf-8-sig').splitlines():
        if '\t' in line:
            left, value = line.split('\t', 1); phase, name = left.split(':', 1)
            if value.lower().startswith('0x'): value = [int(n, 16) for n in value.split()]
            phases.setdefault(phase, {})[name] = value
        elif ':control:' in line:
            phase, _, number, kind, level, stored, visible, name, low, high, mode = line.split(':')
            controls.setdefault(phase, []).append(dict(widget=int(number), group_name=base64.b64decode(name).decode(),
                visible=visible == 'True', level=int(level), stored_level=int(stored)))
    return phases, controls


def options(case):
    result = {}; edits = 0
    if case['name'].startswith('missing-') and case['name'] != 'missing-tail': return None, 'missing-cache-facts'
    for action in case['actions']:
        words = action.split()
        if words[0] in ('groups', 'refresh', 'validate', 'write'): continue
        if words[0] == 'force-edit': return None, 'programmatic-hidden-control-diagnostic'
        if words[0] == 'edit':
            edits += 1
            if edits > 1: return None, 'multiple-edit-sequence'
            widget, level = map(int, words[1:3])
            if not 0 <= level <= 255: return None, 'original-clamping-outside-typed-byte-range'
            result.update(widget=widget, level=level, synchronise=words[3] == 'true')
        elif words[0] == 'mode':
            if edits: return None, 'page-change-after-edit'
            result['page_mode'] = 'multiple' if words[1] == '1' else 'single'
        elif words[0] == 'restore-mode':
            if edits: return None, 'restore-mode-change-after-edit'
            result['restore_mode'] = words[1]
        else: raise ValueError('Unknown original action: ' + action)
    if case['name'] in ('previous-mode-rejected-edit', 'hidden-widget-rejected-edit'): return None, 'original-control-not-editable'
    return result, None


def compact(directories):
    output = dict(format='cbus-edlt-restore-windows-vectors-v1', observations=[], vectors=[], exclusions=[],
                  full_form_initialization_verified=False, physical_device_verified=False)
    baseline = None
    for directory in directories:
        raw = (directory / 'research.json').read_bytes(); document = json.loads(raw)
        for name, wanted in document['input_sha256'].items():
            if digest((directory / name).read_bytes()) != wanted: raise ValueError('Research input changed: ' + name)
        output['observations'].append(dict(directory=directory.name, research_sha256=digest(raw),
            input_sha256=document['input_sha256'], compiled_executable_sha256=document['compiled_executable_sha256'],
            vendor_manifest=document['vendor_manifest']))
        executions = {row['case']: row for row in document['executions']}
        if len(executions) != len(document['cases']): raise ValueError('Incomplete research run')
        for case in document['cases']:
            execution = executions[case['name']]
            stdout = (directory / (case['name'] + '.stdout.txt')).read_bytes()
            stderr = (directory / (case['name'] + '.stderr.txt')).read_bytes()
            if digest(stdout) != execution['stdout_sha256'] or digest(stderr) != execution['stderr_sha256']:
                raise ValueError('Original output changed: ' + case['name'])
            phases, controls = parse(stdout)
            selected, exclusion = options(case)
            if exclusion:
                output['exclusions'].append(dict(case=case['name'], reason=exclusion,
                    original_exit_code=execution['exit_code'], stdout_sha256=digest(stdout))); continue
            if execution['exit_code'] != 0 or stderr or 'complete:true' not in stdout.decode().splitlines():
                raise ValueError('Original success required: ' + case['name'])
            initial = phases['initial']; last = list(controls)[-1]
            if baseline is None: baseline = initial; output['baseline'] = initial
            expected = {label: phases[phase] for label, phase in
                (('after_load', 'afterload'), ('after_controls', last), ('before_save', 'beforesave'), ('final', 'crc'))}
            if any(len(values) != 874 or set(values) != set(initial) for values in expected.values()):
                raise ValueError('Incomplete original parameter phase')
            output['vectors'].append(dict(case=case['name'], cache=case['cache'], options=selected,
                initial={k: v for k, v in initial.items() if v != baseline[k]},
                phases={phase: {k: v for k, v in values.items() if v != initial[k]} for phase, values in expected.items()},
                controls=controls[last], job_id=execution['job_id'], stdout_sha256=digest(stdout)))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path); parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); document = compact(args.directories)
    with args.output.open('x') as target: json.dump(document, target, indent=2); target.write('\n')
    print(json.dumps({'vectors': len(document['vectors']), 'exclusions': len(document['exclusions'])}))
