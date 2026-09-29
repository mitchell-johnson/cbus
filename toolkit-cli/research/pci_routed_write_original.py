"""Original C-Gate routed WRITE acknowledgement matcher matrix.

The Java probe drives the unchanged C-Gate 3.4.0 build 2001 WRITE command
(`ct`), received-message (`cj`) and counter (`cr`) classes over constructed
network/unit caches. Sender, receiver and network dispatch are never invoked.
This module generates the bounded case matrix, runs one fresh original process
without retry, and extracts the per-case native decision summary committed in
`fixtures/pci-routed-write-original-vectors.json`.
"""
import base64
import hashlib
import json

from research.pci_routed_recall_original import Failures, digest, run_process, semantic, semantic_digest

FORMAT = 'pci-routed-write-original-vectors-v1'
SOURCE = 'research/NativeRoutedWriteProbe.java'
FIXTURE = 'research/fixtures/pci-routed-write-original-vectors.json'

UNIT = 4
LOCAL = 0x10
PARAMETER = 35
KEY = 70
DATA = (0x41, 0x42)
REPLY_BRIDGES = tuple(range(20, 26))
OUTGOING_BRIDGES = tuple(range(40, 46))
ALL_DEPTHS = tuple(range(7))
EDGE_DEPTHS = (0, 1, 6)


def frame(route_depth=0, *, cal, header=0x86, outer=None, destination=LOCAL, entries=None,
          checksum=True, lowercase=False, extra=b''):
    """Build one received reply-network frame as original ASCII hex without CR."""
    if entries is None:
        entries = tuple(REPLY_BRIDGES[1:route_depth]) + ((UNIT,) if route_depth else ())
    if outer is None:
        outer = REPLY_BRIDGES[0] if route_depth else UNIT
    body = bytes((header, outer, destination, len(entries), *entries)) + bytes(cal) + extra
    total = (-sum(body)) & 255
    if not checksum:
        total = (total + 1) & 255
    text = (body + bytes((total,))).hex().upper()
    return text.lower() if lowercase else text


def cache(depth, *, last_network=None):
    rows = []
    for index in range(depth):
        target = index + 1
        if index == depth - 1 and last_network is not None:
            target = last_network
        rows.append(f'{index}:{REPLY_BRIDGES[index]}=B{target}')
    return ';'.join(rows) or '-'


def case(identifier, depth, raws, operations, *, family, key=KEY, data=DATA, n=True, t=False,
         cache_text=None, expected=None):
    """One case; `bridges` is the native k(int) call order (last hop first)."""
    outgoing = OUTGOING_BRIDGES[:depth]
    if expected is None:
        expected = {'outer_source_byte': REPLY_BRIDGES[0] if depth else UNIT, 'destination_byte': LOCAL,
                    'route_entries': list(REPLY_BRIDGES[1:depth]) + ([UNIT] if depth else [])}
    return {'id': identifier, 'family': family, 'depth': depth, 'unit': UNIT, 'parameter': PARAMETER,
            'key': key, 'data': list(data), 'bridges': list(reversed(outgoing)), 'outgoing': list(outgoing),
            'root': 0, 'context': depth, 'cache': cache(depth) if cache_text is None else cache_text,
            'n': n, 't': t, 'active': True, 'tag': 'g', 'raws': list(raws), 'operations': list(operations),
            'python_expected': expected}


def ack(parameter=PARAMETER, key=KEY):
    return (0x32, parameter, key)


def cases():
    rows = []
    add = rows.append
    for d in ALL_DEPTHS:
        add(case(f'nominal-d{d}', d, [frame(d, cal=ack())], ['Cg.', 'R0L'], family='nominal'))
        add(case(f'ack-first-n1-d{d}', d, [frame(d, cal=ack())], ['R0L', 'Cg.'], family='ack-before-confirmation'))
        add(case(f'ack-first-n0-d{d}', d, [frame(d, cal=ack())], ['R0L', 'Cg.'], n=False, family='nominal'))
        add(case(f'wrong-parameter-d{d}', d, [frame(d, cal=ack(PARAMETER + 1))], ['Cg.', 'R0L'], family='wrong-parameter'))
        add(case(f'wrong-tag-d{d}', d, [frame(d, cal=ack(key=KEY + 1))], ['Cg.', 'R0L'], family='wrong-tag'))
        entries = tuple(REPLY_BRIDGES[1:d]) + ((UNIT + 1,) if d else ())
        add(case(f'wrong-unit-d{d}', d, [frame(d, cal=ack(), outer=None if d else UNIT + 1, entries=entries)],
                 ['Cg.', 'R0L'], family='wrong-unit'))
        for size in (0, 29):
            add(case(f'data-{size}-d{d}', d, [frame(d, cal=ack())], ['Cg.', 'R0L'], data=tuple(range(1, size + 1)),
                     family='nominal'))
    for d in range(1, 7):
        add(case(f'wrong-first-bridge-d{d}', d, [frame(d, cal=ack(), outer=31)], ['Cg.', 'R0L'], family='wrong-route'))
        if d > 1:
            entries = (30,) + tuple(REPLY_BRIDGES[2:d]) + (UNIT,)
            add(case(f'wrong-middle-bridge-d{d}', d, [frame(d, cal=ack(), entries=entries)], ['Cg.', 'R0L'],
                     family='wrong-route'))
        short = frame(d, cal=ack(), entries=tuple(REPLY_BRIDGES[1:d - 1]) + (UNIT,)) if d > 1 else frame(0, cal=ack())
        add(case(f'short-route-d{d}', d, [short], ['Cg.', 'R0L'], family='wrong-route'))
        add(case(f'cached-network-identity-d{d}', d, [frame(d, cal=ack())], ['Cg.', 'R0L'],
                 cache_text=cache(d, last_network=7), family='cached-network-identity'))
        add(case(f'bare-ack-d{d}', d, [bytes(ack()).hex().upper()], ['Cg.', 'R0S'], family='bare-ack'))
    add(case('bare-ack-d0', 0, [bytes(ack()).hex().upper()], ['Cg.', 'R0S'], family='bare-ack'))
    for d in EDGE_DEPTHS:
        add(case(f'unconfirmed-n0-d{d}', d, [frame(d, cal=ack())], ['R0L'], n=False, family='confirmation-required'))
        add(case(f'ack-first-repeated-n1-d{d}', d, [frame(d, cal=ack())], ['R0L', 'Cg.', 'R0L'],
                 family='ack-before-confirmation'))
        add(case(f'destination-d{d}', d, [frame(d, cal=ack(), destination=LOCAL + 1)], ['Cg.', 'R0L'],
                 family='destination'))
        add(case(f'checksum-d{d}', d, [frame(d, cal=ack(), checksum=False)], ['Cg.', 'R0L'], family='checksum'))
        add(case(f'negative-3b-d{d}', d, [frame(d, cal=(0x3B, PARAMETER, KEY))], ['Cg.', 'R0L'], family='negative'))
        add(case(f'negative-3b-wrong-tag-d{d}', d, [frame(d, cal=(0x3B, PARAMETER, KEY + 1))], ['Cg.', 'R0L'],
                 family='wrong-tag'))
        add(case(f'trailing-cal-d{d}', d, [frame(d, cal=ack(), extra=bytes((0x32, 0, 0)))], ['Cg.', 'R0L'],
                 family='trailing-cal'))
        add(case(f'alpha-tag-d{d}', d, [frame(d, cal=ack(key=0xAB))], ['Cg.', 'R0L'], key=0xAB, family='nominal'))
        add(case(f'lowercase-d{d}', d, [frame(d, cal=ack(key=0xAB), lowercase=True)], ['Cg.', 'R0L'], key=0xAB,
                 family='lowercase-hex'))
        add(case(f'duplicate-ack-d{d}', d, [frame(d, cal=ack())], ['Cg.', 'R0L', 'R0L'], family='duplicate'))
        add(case(f'duplicate-confirmation-d{d}', d, [frame(d, cal=ack())], ['Cg.', 'Cg.', 'R0L'], family='duplicate'))
        add(case(f'other-confirmation-tag-d{d}', d, [frame(d, cal=ack())], ['Ch.', 'R0L'], family='confirmation-tag'))
        for status, name in (('#', 'hash'), ('$', 'dollar'), ('%', 'percent')):
            add(case(f'confirmation-{name}-t0-d{d}', d, [frame(d, cal=ack())], ['Cg' + status, 'R0L'],
                     family='negative-confirmation'))
        add(case(f'confirmation-hash-t1-d{d}', d, [frame(d, cal=ack())], ['Cg#', 'R0L'], t=True,
                 family='hash-confirmation'))
        for header in (0x06, 0x0E, 0x46, 0xC6, 0x85):
            add(case(f'header-{header:02x}-d{d}', d, [frame(d, cal=ack(), header=header)], ['Cg.', 'R0L'],
                     family='nominal' if header == 0x06 else 'header'))
    entries = tuple(REPLY_BRIDGES[1:6]) + (26, UNIT)
    add(case('route-count-7', 6, [frame(6, cal=ack(), entries=entries)], ['Cg.', 'R0L'], family='route-count'))
    return rows


TSV_KEYS = ('id', 'unit', 'parameter', 'key', 'data', 'bridges', 'root', 'context', 'cache', 'n', 't', 'active',
            'tag', 'raws', 'operations')


def plan_tsv(plans):
    lines = []
    for c in plans:
        values = [c['id'], str(c['unit']), str(c['parameter']), str(c['key']), ','.join(map(str, c['data'])) or '-',
                  ','.join(map(str, c['bridges'])) or '-', str(c['root']), str(c['context']), c['cache'],
                  str(int(c['n'])), str(int(c['t'])), str(int(c['active'])), c['tag'],
                  ','.join(base64.b64encode(raw.encode('ascii')).decode('ascii') for raw in c['raws']),
                  ';'.join(c['operations']) or '-']
        lines.append('\t'.join(values))
    return ('\n'.join(lines) + '\n').encode('ascii')


def native_summary(row):
    """Decision fields a WRITE caller observes; the full row stays behind its semantic hash."""
    return {'results': [a.get('result') if a['completed'] else None for a in row['actions']],
            'errors': [a['error']['class'] for a in row['actions'] if not a['completed']],
            'prepend_accepted': [p['accepted'] for p in row['prepend']],
            'command': row['prepend'][-1]['after'] if row['prepend'] else row['configured']['command'],
            'constructor': [m['constructor_complete'] for m in row['messages']],
            'received': row['received'], 'negative': row['negative'], 'confirmed': row['confirmed'],
            'acknowledgements': row['acknowledgements'],
            'negative_acknowledgements': row['negative_acknowledgements']}


def native_success(summary, plan):
    """Original caller success: response complete, not negative, confirmed when required."""
    return summary['received'] and not summary['negative'] and (summary['confirmed'] or not plan['n'])


def _execute(root, *, java, javac, jar, destination, plans, source):
    from pathlib import Path
    import shutil
    import sys
    data = plan_tsv(plans)
    paths = [source, Path(__file__).resolve(), java, javac, jar, java.parent.parent / 'lib/modules',
             Path(sys.executable).resolve()]
    before = {str(p): digest(p) for p in paths}
    destination.mkdir(exist_ok=False)
    failures = Failures()
    report = {'format': 'pci-routed-write-fresh-original-v1', 'passed': False, 'python_version': sys.version,
              'python_executable': sys.executable, 'inputs_before': before, 'network_denied': True,
              'processes': [], 'vm_or_shared_service_used': False, 'tsv_sha256': hashlib.sha256(data).hexdigest()}
    compiled = []
    rows = None
    try:
        for name in ('tmp', 'home'):
            (destination / name).mkdir()
        shutil.copyfile(source, destination / source.name)
        assert digest(destination / source.name) == before[str(source)]
        (destination / 'input.tsv').write_bytes(data)
        profile = destination / 'network-denied.sb'
        profile.write_text('(version 1)\n(allow default)\n(deny network*)\n')
        sandbox = ['/usr/bin/sandbox-exec', '-f', str(profile)]
        commands = [sandbox + [str(javac), '-encoding', 'UTF-8', '-classpath', str(jar), '-d', str(destination),
                               str(destination / source.name)],
                    sandbox + [str(java), '-XX:-UsePerfData', '-Djava.io.tmpdir=' + str(destination / 'tmp'),
                               '-Duser.home=' + str(destination / 'home'), '-Djava.awt.headless=true',
                               '-classpath', str(destination) + ':' + str(jar), 'NativeRoutedWriteProbe',
                               str(destination / 'input.tsv'), str(destination)]]
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(destination / 'home'),
                       'TMPDIR': str(destination / 'tmp') + '/', 'LANG': 'en_US.UTF-8'}
        for stage, command in zip(('compile', 'original'), commands):
            if stage == 'original':
                compiled = [destination / source.name, destination / 'input.tsv', profile,
                            *sorted(destination.glob('*.class'))]
                report['compiled_before'] = {p.name: digest(p) for p in compiled}
            process = run_process(stage, command, destination=destination, environment=environment,
                                  failures=failures)
            report['processes'].append(process)
            failures.raise_first()
            assert process['exit_code'] == 0
        assert (destination / 'original.stderr').read_bytes() == b''
        rows = [json.loads(line) for line in (destination / 'original.stdout').read_text().splitlines()]
        assert rows[-1] == {'kind': 'complete', 'cases': len(plans)} and len(rows) == len(plans) + 2
        for row, plan in zip(rows[1:-1], plans):
            assert row['id'] == plan['id']
            for action in row['actions']:
                start, end = action['utc_milliseconds_before'], action['utc_milliseconds_after']
                assert type(start) is type(end) is int and start <= end
                if action['after']['aW.N'] != action['before']['aW.N']:
                    assert start <= action['after']['aW.N'] <= end
        report['cases'] = len(plans)
        report['passed'] = True
    except BaseException as error:
        if failures.first is not error:
            failures.remember('original_execution_or_comparison', error)
    finally:
        def verify():
            report['inputs_after'] = {str(p): digest(p) for p in paths}
            assert report['inputs_after'] == before
            report['inputs_unchanged'] = True
            if compiled:
                report['compiled_after'] = {p.name: digest(p) for p in compiled}
                assert report['compiled_after'] == report['compiled_before']
                report['compiled_unchanged'] = True
        failures.attempt('verify_original_inputs', verify)

        def artifacts():
            report['artifacts'] = {str(p.relative_to(destination)): digest(p)
                                   for p in destination.rglob('*') if p.is_file()}
        failures.attempt('hash_artifacts', artifacts)
        report['passed'] = report['passed'] and failures.first is None
        report['failures'] = list(failures.records)

        def write():
            with (destination / 'report.json').open('x') as stream:
                stream.write(json.dumps(report, indent=2) + '\n')
        failures.attempt('write_report', write)
    failures.raise_first()
    return report, rows


def _resolved(root, java, javac, jar, destination):
    from pathlib import Path
    import sys
    if sys.platform != 'darwin' or sys.version_info[:2] not in ((3, 10), (3, 13)):
        raise ValueError('Explicit macOS Python3.10/3.13 original probe required')
    root = Path(root).resolve(strict=True)
    java, javac, jar = (Path(p).resolve(strict=True) for p in (java, javac, jar))
    destination = Path(destination).absolute()
    if destination.parent.resolve(strict=True) != destination.parent:
        raise ValueError('Original output parent must be an existing resolved directory')
    return root, java, javac, jar, destination


def build_fixture(root, *, java, javac, jar, destination):
    """Research-only: run the generated matrix once and write the sanitized fixture."""
    root, java, javac, jar, destination = _resolved(root, java, javac, jar, destination)
    plans = cases()
    assert len({p['id'] for p in plans}) == len(plans) <= 512
    source = root / SOURCE
    report, rows = _execute(root, java=java, javac=javac, jar=jar, destination=destination, plans=plans,
                            source=source)
    fixture = {'format': FORMAT, 'source_sha256': digest(source), 'jar_sha256': digest(jar),
               'tsv_sha256': hashlib.sha256(plan_tsv(plans)).hexdigest(),
               'original_report_sha256': digest(destination / 'report.json'),
               'original_stdout_sha256': digest(destination / 'original.stdout'),
               'semantic_normalization': 'All original fields retained behind semantic_sha256; per-action UTC '
                                         'bounds excluded; positive aW.N replaced by a named timestamp marker and '
                                         'separately range-checked in fresh runs.',
               'runtime': rows[0],
               'cases': [{'input': plan, 'native': native_summary(row), 'semantic_sha256': semantic_digest(row)}
                         for plan, row in zip(plans, rows[1:-1])]}
    (root / FIXTURE).write_text(json.dumps(fixture, indent=1, sort_keys=True) + '\n')
    return fixture


def run_original(root, *, java, javac, jar, destination):
    """Fresh complete matrix compared case by case with the committed semantic hashes."""
    root, java, javac, jar, destination = _resolved(root, java, javac, jar, destination)
    fixture = json.loads((root / FIXTURE).read_text())
    source = root / SOURCE
    assert digest(source) == fixture['source_sha256']
    assert digest(jar) == fixture['jar_sha256']
    plans = [r['input'] for r in fixture['cases']]
    assert hashlib.sha256(plan_tsv(plans)).hexdigest() == fixture['tsv_sha256']
    report, rows = _execute(root, java=java, javac=javac, jar=jar, destination=destination, plans=plans,
                            source=source)
    assert rows[0] == fixture['runtime']
    for row, expected in zip(rows[1:-1], fixture['cases']):
        assert semantic_digest(row) == expected['semantic_sha256'], row['id']
        assert native_summary(row) == expected['native'], row['id']
    report['comparisons'] = len(plans)
    return report


__all__ = ['cases', 'plan_tsv', 'frame', 'native_summary', 'native_success', 'build_fixture', 'run_original',
           'semantic', 'semantic_digest']
