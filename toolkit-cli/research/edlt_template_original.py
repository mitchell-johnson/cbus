"""Bounded synthetic evidence from unchanged original template CRC helpers.

This invokes no Toolkit form or parent lifecycle. XML and Application cases use
the original framework operations observed in fresh IL, rather than claiming an
execution of TemplatesDialog. No assemblies or vendor specs are published.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

DLL_SHA256 = '34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823'
PINS = {
    'bin/mono-sgen64': '91b99fc4b1158785b43506f2d76f9998c31f0492128e5789fbaaab0e300afd49',
    'lib/mono/4.5/mcs.exe': '857bb3129c3e2a5e7f8410db8fa5eb78139e934bb6279a72428597962311d771',
    'lib/mono/4.5/mscorlib.dll': '86364b7803c92d8c88b590031f015f80b10b00641e9d067e07a529a131d815e4',
}
METHODS = {
    'CalcTemplateCrc': ('0x0600066e', 'fa1264636fafa5bb7062cf8ceadc3da7a2340f27e0474169e52df7cbdaf58c64'),
    'CalculateCrcForTemplate': ('0x0600066f', '906c4e3e493f55ce91b1e439dd9c231987e564a84a3e27f5d1fd9f4f06d3d9d1'),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cases():
    rows = []
    values = [
        ('empty', []), ('empty-value', ['']), ('space-only', [' \t\r\n']),
        ('single-A', ['A']), ('two-AB', ['AB']), ('two-AC', ['AC']),
        ('split-AB', ['A', 'B']), ('three-ABC', ['ABC']),
        ('trim-each', ['  A ', '\tBC\r\n']), ('hex', ['0x30 0xca']),
        ('decimal-equivalent', ['48 202']), ('leading-hex-space', [' 0x30 0xca']),
        ('uppercase-prefix', ['0X30 0xca']), ('hex-double-space', ['0x30  0xca']),
        ('hex-trailing-space', ['0x30 ']), ('hex-tab', ['0x30\t0xca']),
        ('hex-bare-following', ['0x30 ca']), ('hex-plus', ['0x30 +CA']),
        ('hex-negative', ['0x30 -1']), ('hex-signed-max', ['0x7fffffff']),
        ('hex-signed-min', ['0x80000000']), ('hex-negative-one', ['0xffffffff']),
        ('signed-min-decimal', ['-2147483648']), ('negative-one-decimal', ['-1']),
        ('hex-overflow', ['0x100000000']), ('hex-empty', ['0x']),
        ('hex-prefix-leading-nul', ['\x000x30 0xca']),
        ('hex-prefix-middle-nul', ['0\x00x30 0xca']),
        ('hex-prefix-zero-width-space', ['\u200b0x30 0xca']),
        ('hex-prefix-middle-zwj', ['0\u200dx30 0xca']),
        ('hex-prefix-middle-zwnj', ['0\u200cx30 0xca']),
        ('hex-prefix-soft-hyphen', ['\u00ad0x30 0xca']),
        ('hex-following-plus-prefix', ['0x30 +0xCA']),
        ('hex-following-upper-prefix', ['0x30 0XCA']),
        ('hex-following-plus-upper-prefix', ['0x30 +0XCA']),
        ('hex-token-trailing-nul', ['0x30\x00 0xca']),
        ('unicode-low-byte-A', ['\u0141B']), ('unicode-A', ['AB']),
        ('unicode-surrogate', ['\U0001f600Z']), ('surrogate-low-equivalent', ['=\x00Z']),
        ('unicode-trim-nbsp', ['\u00a0AB\u00a0']), ('unicode-trim-next-line', ['\u0085AB\u0085']),
        ('unicode-no-trim-python-controls', ['\u001cAB\u001c']), ('unicode-trim-em-space', ['\u2003AB\u2003']),
        ('unicode-no-trim-zero-width', ['\u200bAB\u200b']), ('xml-entity-string', ['A&amp;B']),
        ('ordered-a', ['48 202', '5.5.00', 'Synthetic', 'KEYGL5', '0x01 0xff']),
        ('ordered-b', ['48 202', '5.5.00', 'KEYGL5', 'Synthetic', '0x01 0xff']),
        ('buffer-exact', ['A' * 65536]), ('buffer-overflow', ['A' * 65537]),
    ]
    rows.extend({'id': name, 'kind': 'crc', 'values': value} for name, value in values)
    for name, start, length in [('raw-full', 0, 4), ('raw-start-one', 1, 4), ('raw-start-one-len-two', 1, 2), ('raw-zero', 0, 0)]:
        rows.append({'id': name, 'kind': 'raw', 'bytes': [1, 2, 3, 4], 'start': start, 'length': length})
    for name, value in [('normal', '48 202'), ('empty', ''), ('repeated-space', '48  202'), ('leading-space', ' 48 202'), ('trailing-space', '48 202 '), ('tab', '48\t202'), ('negative', '-1 2147483647'), ('plus', '+48 202'), ('hex', '0x30 202'), ('overflow', '2147483648'), ('newline', '48\n202')]:
        rows.append({'id': 'app-' + name, 'kind': 'application', 'value': value})
    xmls = [
        ('xml-inner', '<UnitTemplate>\n<X>A&amp;B&#x41;&quot;&apos;</X><Y><nested a="&quot;"/></Y><Z><![CDATA[A&B]]></Z><!--comment--><?test value?><Q> \n </Q></UnitTemplate>'),
        ('xml-preserve', '<UnitTemplate xml:space="preserve">\n<X> A </X>\n</UnitTemplate>'),
        ('xml-line-endings', '<UnitTemplate><X>A\r\nB\rC\nD&#13;E&#10;F</X><Y>a&gt;b > c</Y></UnitTemplate>'),
        ('xml-duplicate-headers', '<UnitTemplate><UnitType>WRONG</UnitType><UnitType>KEYGL5</UnitType><FirmwareVersion> </FirmwareVersion><CRC>65261</CRC><UnitType>OTHER</UnitType></UnitTemplate>'),
        ('xml-entity-dtd', '<!DOCTYPE UnitTemplate [<!ENTITY x "hello">]><UnitTemplate><X>&x;</X></UnitTemplate>'),
        ('xml-scalar-template', '<UnitTemplate>\r\n<Description>Synthetic</Description><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion><CRC>0</CRC><Application>48 202</Application><FirmwareVersion>5.5.00</FirmwareVersion><UnitName>Synthetic</UnitName><UnitType>KEYGL5</UnitType><X>0x01 0xff</X></UnitTemplate>'),
        ('xml-scalar-entities', '<UnitTemplate><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion><CRC>0</CRC><X>A&amp;B&#x41;&quot;&apos;&gt;</X><Y>A\r\nB\rC\nD&#13;E&#10;F</Y><Z>\u0141\U0001f600</Z></UnitTemplate>'),
        ('xml-second-crc', '<UnitTemplate><UnitType>KEYGL5</UnitType><FirmwareVersion>5.5.00</FirmwareVersion><CRC>0</CRC><X>A</X><CRC>123</CRC><X>B</X></UnitTemplate>'),
    ]
    rows.extend({'id': name, 'kind': 'xml', 'value': value} for name, value in xmls)
    return rows


def encoded(value):
    return base64.b64encode(value.encode('utf-16-le')).decode('ascii')


def decode(value):
    return base64.b64decode(value, validate=True).decode('utf-16-le')


def input_line(row):
    fields = [row['kind'], row['id']]
    if row['kind'] == 'crc':
        fields.extend(map(encoded, row['values']))
    elif row['kind'] == 'raw':
        fields.extend((base64.b64encode(bytes(row['bytes'])).decode('ascii'), str(row['start']), str(row['length'])))
    else:
        fields.append(encoded(row['value']))
    return '\t'.join(fields)


def probe(logic_dll, mono_root, destination):
    dll, mono, out = Path(logic_dll).resolve(), Path(mono_root).resolve(), Path(destination).absolute()
    if digest(dll) != DLL_SHA256:
        raise ValueError('Requires pinned original CBusLogicModel.dll')
    for name, expected in PINS.items():
        if digest(mono / name) != expected:
            raise ValueError('Requires pinned owned Mono: ' + name)
    source = Path(__file__).with_name('edlt_template_original_probe.cs')
    tracked = [Path(__file__).resolve(), source, dll, *(mono / name for name in PINS)]
    before = {str(path): digest(path) for path in tracked}
    out.mkdir()
    rows = cases()
    (out / 'input.tsv').write_text('\n'.join(map(input_line, rows)) + '\n', encoding='ascii')
    env = {key: value for key, value in os.environ.items() if not key.startswith(('CBUS_', 'MONO_', 'DYLD_')) and key not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(MONO_CFG_DIR=str(mono / 'etc'), MONO_PATH=str(dll.parent) + os.pathsep + str(mono / 'lib/mono/4.5'), DYLD_FALLBACK_LIBRARY_PATH=str(mono / 'lib'))
    runtime = [str(mono / 'bin/mono-sgen64')]
    commands = [
        ('compile', runtime + [str(mono / 'lib/mono/4.5/mcs.exe'), '-r:' + str(dll), '-out:' + str(out / 'Probe.exe'), str(source)]),
        ('run', runtime + [str(out / 'Probe.exe'), str(out / 'input.tsv')]),
    ]
    report = {'format': 'cbus-edlt-template-original-v1', 'passed': False, 'scope': 'Unchanged PPHelper static CRC helpers; framework XML/Application operation probes, no original form execution', 'commands': [], 'before': before}
    try:
        for stage, command in commands:
            command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', *command]
            result = subprocess.run(command, env=env, capture_output=True, timeout=30)
            (out / (stage + '.stdout')).write_bytes(result.stdout)
            (out / (stage + '.stderr')).write_bytes(result.stderr)
            report['commands'].append({'stage': stage, 'returncode': result.returncode, 'network_denied': True})
            if result.returncode:
                raise RuntimeError('Original template probe failed: ' + stage)
        lines = (out / 'run.stderr').read_text().splitlines()
        paths = [dll, mono / 'lib/mono/4.5/mscorlib.dll', out / 'Probe.exe']
        names = ['CBusLogicModel.PPHelper', 'System.Object', 'EdltTemplateOriginalProbe']
        if len(lines) != 5:
            raise AssertionError('Unexpected runtime evidence')
        for line, path, name in zip(lines[:3], paths, names):
            prefix, actual_name, actual_path, actual_hash, bits = line.split('\t')
            if (prefix, actual_name, Path(actual_path).resolve(), actual_hash, bits) != ('assembly', name, path.resolve(), digest(path), '64'):
                raise AssertionError('Wrong runtime loaded')
        for line, (name, expected) in zip(lines[3:], METHODS.items()):
            if line.split('\t') != ['method', name, *expected]:
                raise AssertionError('Original method IL changed')
        results = {row['id']: {**row, 'observations': []} for row in rows}
        for line in (out / 'run.stdout').read_text().splitlines():
            fields = line.split('\t')
            row = results[fields[0]]
            if fields[1] == 'node':
                observation = {'node_type': fields[2], 'name': decode(fields[3]), 'inner_xml': decode(fields[4])}
            elif fields[1] == 'error':
                observation = {'error': fields[2]}
            elif fields[1] == 'checksum':
                observation = {'post_first_crc_checksum': int(fields[2])}
            else:
                observation = {'value': decode(fields[2]) if row['kind'] == 'application' else int(fields[2])}
            row['observations'].append(observation)
        if any(not row['observations'] for row in results.values()):
            raise AssertionError('Missing case result')
        report['runtime'] = lines
        report['cases'] = list(results.values())
        report['after'] = {str(path): digest(path) for path in tracked}
        if report['after'] != before:
            raise AssertionError('Inputs mutated')
        report['passed'] = True
    except BaseException as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        report['artifacts'] = {path.name: digest(path) for path in out.iterdir() if path.is_file()}
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def verify_fixture(report, fixture_path):
    """Compare fresh observations to the retained original literal vectors."""
    fixture = json.loads(Path(fixture_path).read_text())
    expected = []
    for source in fixture['cases']:
        row = dict(source)
        if 'values_repeated' in row:
            row['values'] = [item['text'] * item['count'] for item in row.pop('values_repeated')]
        expected.append(row)
    if report['cases'] != expected:
        raise AssertionError('Fresh original observations differ from fixture')
    return len(expected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logic-dll', required=True)
    parser.add_argument('--mono-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--verify-fixture')
    args = parser.parse_args()
    result = probe(args.logic_dll, args.mono_root, args.output)
    verified = verify_fixture(result, args.verify_fixture) if args.verify_fixture else None
    print(json.dumps({'passed': result['passed'], 'cases': len(result['cases']), 'fixture_cases_verified': verified, 'output': args.output}))
