"""Native generic-GET inventory for an open synthetic KEYGL5 (P6.05).

The committed fixture was captured from owned C-Gate 3.4.0.2001 against the
PCI simulator. The offline tests check its internal consistency and bind its
property inventory to the independently derived constructor-registration
audit. The native class repeats the capture and compares the sanitized
command replies; simulator frames are checked by request class only because
native background polling may interleave with a command window.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import unittest

from research import edlt_open_unit_native as probe

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/edlt-open-unit-get-native.json'
INHERITANCE = ROOT / 'research/fixtures/edlt-dynamic-cache-get-inheritance.json'
LABEL_LIKE = re.compile(r'label|cache|dynamic|text|kfi', re.IGNORECASE)
# Optional smart-mode header 46 <unit> 00; CAL opcodes allowed per probe kind.
READ_CAL = re.compile(r'^(?:46[0-9A-F]{2}00)?(?:1A[0-9A-F]{4}|21[0-9A-F]{2})+$')
KFI_CAL = re.compile(r'^(?:46[0-9A-F]{2}00)?(?:A[0-9A-F]FF[0-9A-F]+|213D)$')


def _rows(report):
    return {row['command']: row for row in report['probes']}


def _names(lines, marker):
    return [re.match(rf'^\d{{3}}[- ]\S+: (\w+){marker}', line).group(1) for line in lines]


def check_report(report):
    """Raise AssertionError unless the report shows an open eDLT with no label getter."""
    rows = _rows(report)
    unit = probe.UNIT
    for row in report['setup']:
        assert row['lines'][-1][:3] in ('200', '301'), row
    assert report['cleanup_errors'] == []
    listed = rows[f'GET {unit} ?']['lines']
    assert len(listed) == 1 and listed[0].startswith(f'300 {unit}: Parameters=')
    listed = listed[0].split('=', 1)[1].split(',')
    described = _names(rows[f'GET {unit} ??']['lines'], ' - ')
    values = dict(re.match(r'^300[- ]\S+: (\w+)=(.*)$', line).groups()
                  for line in rows[f'GET {unit} *']['lines'])
    assert len(listed) == len(set(listed)) == 30
    assert set(listed) == set(described) == set(values)
    assert (values['State'], values['Type'], values['Version'], values['ClassName']) == \
        ('ok', 'KEYGL5', '5.5.00', 'com.clipsal.cgate.cbus.dev.CBusEdlt')
    chain = json.loads(INHERITANCE.read_text())['source']['class_chain']
    assert set(listed) == {name for row in chain for name in row['properties']}
    assert not [name for name in listed if LABEL_LIKE.search(name)]
    for name in probe.CANDIDATES:
        assert rows[f'GET {unit} {name}']['lines'] == [
            f'402 Operation not supported by: {unit} (Parameter {name.lower()} not found)']
    for path in (f'{probe.NETWORK}/56', f'{probe.NETWORK}/56/27'):
        described = _names(rows[f'GET {path} ??']['lines'], ' - ')
        assert set(described) == set(_names(rows[f'GET {path} *']['lines'], '='))
        assert not [name for name in described if LABEL_LIKE.search(name)]
    kfi = rows[f'LABEL KFIGET {probe.NETWORK}/56 5']
    expected = [n for byte in probe.KFI_BYTES for n in (byte & 15, byte >> 4)]
    assert kfi['lines'] == [f'300{"-" if i < 8 else " "}kfi{i}={v}' for i, v in enumerate(expected, 1)]
    for command, row in rows.items():
        requests = [w['frame'] for w in row['wire'] if w['direction'] == 'rx']
        assert not [w for w in row['wire'] if 'rejected' in w], command
        pattern = KFI_CAL if command.startswith('LABEL KFIGET') else READ_CAL
        assert all(pattern.fullmatch(frame) for frame in requests), (command, requests)
    assert [w['frame'] for w in kfi['wire'] if w['direction'] == 'rx'][-1] == '213D'


def _comparable(report):
    report = deepcopy(report)
    for row in report['probes']:
        row.pop('wire')
    for key in ('native', 'probe_sha256'):
        report.pop(key, None)
    return report


class FixtureTests(unittest.TestCase):
    def test_fixture_shows_open_unit_with_bounded_inventory(self):
        check_report(json.loads(FIXTURE.read_text()))

    def test_fixture_was_captured_by_this_probe_and_pinned_release(self):
        report = json.loads(FIXTURE.read_text())
        self.assertEqual(report['probe_sha256'], hashlib.sha256(Path(probe.__file__).read_bytes()).hexdigest())
        self.assertEqual(report['native']['cgate_jar_sha256'],
                         '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630')
        self.assertTrue(report['native']['cleanup_complete'])
        text = FIXTURE.read_text()
        self.assertNotRegex(text, r'127\.0\.0\.1:[1-9]')
        self.assertNotRegex(text, r'(?!00000000-0000-4000-8000-000000000000)[0-9a-f]{8}-[0-9a-f]{4}-')

    def test_forged_label_property_or_device_query_is_rejected(self):
        base = json.loads(FIXTURE.read_text())
        edits = []

        def added_property(report):
            row = _rows(report)[f'GET {probe.UNIT} ?']
            row['lines'][0] += ',DynamicLabels'
        edits.append(added_property)

        def candidate_answered(report):
            _rows(report)[f'GET {probe.UNIT} LabelCache']['lines'] = [f'300 {probe.UNIT}: LabelCache=Hall']
        edits.append(candidate_answered)

        def extra_request(report):
            _rows(report)[f'GET {probe.UNIT} *']['wire'].append({'direction': 'rx', 'frame': '4605002A0010'})
        edits.append(extra_request)

        def unopened(report):
            _rows(report)[f'GET {probe.UNIT} ?']['lines'] = [
                f'401 Bad object or device ID: {probe.UNIT} (Unit not found)']
        edits.append(unopened)
        for edit in edits:
            report = deepcopy(base)
            edit(report)
            with self.subTest(edit=edit.__name__), self.assertRaises(AssertionError):
                check_report(report)

    def test_simulator_blocks_are_the_documented_additions(self):
        sim = probe.edlt_simulator()
        unit = sim.units[5]
        self.assertEqual(unit.attributes[1], b'KEYGL5  ')
        self.assertEqual(unit.attributes[2], b'5.5.00  ')
        self.assertEqual(unit.parameters[0x3E], b'\x00')
        self.assertEqual(unit.write_tags, {0: 0x41, 1: 0x42, 0x21: 0, 0xFF: 0})
        self.assertEqual(unit.attributes[0x3D], b'\x80' + probe.KFI_BYTES + bytes(7))


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'), 'Set CBUS_CGATE_TEST_HOST for a disposable native C-Gate')
class NativeOpenUnitGetTests(unittest.TestCase):
    def test_native_capture_reproduces_the_committed_fixture(self):
        report = probe.sanitized(probe.run(
            os.environ['CBUS_CGATE_TEST_HOST'], int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')),
            os.environ.get('CBUS_CGATE_SIMULATOR_HOST', '127.0.0.1'),
            os.environ.get('CBUS_CGATE_SIMULATOR_BIND', '127.0.0.1')))
        check_report(report)
        self.assertEqual(_comparable(report), _comparable(json.loads(FIXTURE.read_text())))


if __name__ == '__main__':
    unittest.main()
