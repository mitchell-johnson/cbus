"""Wave-24 offline pins for unit-diagnostics guards with zero prior test refs.

Covers only guards in ``src/cbus_toolkit/unit_diagnostics.py`` whose exact
message literals no existing test references (verified 2026-10-15 via
``grep -rn`` over ``toolkit-cli/tests/`` for each literal below):
boolean field selection, database XML shape guards, exact PINGU reply
guards, and unit-selection guards. Offline: synthetic DBGETXML/PINGU
replies and an in-memory fake client only, no hardware/network/serial.
"""
import unittest

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.unit_diagnostics import DiagnosticsError, NetworkDiagnostics

NETWORK = '//DIAGNOSE/254'


def _response(lines):
    return CGateResponse(tuple(lines), lines[-1], int(lines[-1][:3]))


class _StubClient:
    """Serve a scripted command/reply sequence; record what was sent."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.sent = []

    def command(self, text):
        self.sent.append(text)
        if not self.rows:
            raise AssertionError('Unexpected extra command: ' + text)
        row = self.rows.pop(0)
        if text != row['command']:
            raise AssertionError(f'Expected {row["command"]!r}, sent {text!r}')
        response = _response(row['lines'])
        if response.status >= 400:
            raise CGateError(response)
        return response


def _xml_body(inner, address='254'):
    return {'command': f'DBGETXML {NETWORK}',
            'lines': [f'347-<Network><Address>{address}</Address>{inner}</Network>',
                      '344 End XML snippet']}


def _xml(units):
    body = ''.join(f'<Unit><Address>{address}</Address>'
                   + (f'<UnitType>{unit_type}</UnitType>' if unit_type else '')
                   + '</Unit>'
                   for address, unit_type in units)
    return _xml_body(body)


def _pingu_lines(first):
    return {'command': f'NET PINGU {NETWORK}', 'lines': [first, '200 OK.']}


class UnitDiagWave24Pins(unittest.TestCase):
    def test_boolean_field_selection_guard_without_io(self):
        for kwargs in ({'voltage': 1}, {'burden': 'yes'}, {'clock': None}):
            client = _StubClient([])
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError,
                                            'Diagnostic field selections must be booleans'):
                    NetworkDiagnostics(client).diagnose(NETWORK, **kwargs)
            self.assertEqual(client.sent, [])

    def test_database_xml_shape_guards(self):
        with self.assertRaisesRegex(DiagnosticsError,
                                    'C-Gate network XML does not match the requested network'):
            NetworkDiagnostics(_StubClient([_xml_body('<Unit><Address>4</Address></Unit>',
                                                      address='253')])).diagnose(NETWORK)
        for bad in ('04', '256', '-1'):
            with self.subTest(address=bad):
                body = (f'<Unit><Address>{bad}</Address><UnitType>KEYE1</UnitType></Unit>')
                with self.assertRaisesRegex(DiagnosticsError,
                                            'Database unit address must be a canonical decimal byte'):
                    NetworkDiagnostics(_StubClient([_xml_body(body)])).diagnose(NETWORK)
        dup_fields = ('<Unit><Address>4</Address><Address>5</Address>'
                      '<UnitType>KEYE1</UnitType></Unit>')
        with self.assertRaisesRegex(DiagnosticsError,
                                    'Database unit has duplicate Address fields'):
            NetworkDiagnostics(_StubClient([_xml_body(dup_fields)])).diagnose(NETWORK)

    def test_pingu_exact_reply_guards(self):
        three_lines = {'command': f'NET PINGU {NETWORK}',
                       'lines': ['302-Units=4', '200 OK.', '200 OK.']}
        with self.assertRaisesRegex(DiagnosticsError,
                                    'Expected an exact successful NET PINGU reply'):
            NetworkDiagnostics(_StubClient([_xml([(4, 'KEYE1')]), three_lines])).diagnose(NETWORK)
        with self.assertRaisesRegex(DiagnosticsError,
                                    'NET PINGU did not return an exact unit address list'):
            rows = [_xml([(4, 'KEYE1')]), _pingu_lines('302-Nope=4')]
            NetworkDiagnostics(_StubClient(rows)).diagnose(NETWORK)
        for first in ('302-Units=4, 4', '302-Units=256'):
            with self.subTest(reply=first):
                rows = [_xml([(4, 'KEYE1')]), _pingu_lines(first)]
                with self.assertRaisesRegex(DiagnosticsError,
                                            'NET PINGU addresses must be unique, ordered decimal'):
                    NetworkDiagnostics(_StubClient(rows)).diagnose(NETWORK)

    def test_unit_selection_guards(self):
        with self.assertRaisesRegex(ValueError, 'Unit selection cannot be empty'):
            NetworkDiagnostics(_StubClient([])).diagnose(NETWORK, units=[])
        with self.assertRaisesRegex(ValueError, 'Unit selection contains duplicate addresses'):
            NetworkDiagnostics(_StubClient([])).diagnose(NETWORK, units=[4, 4])
        for bad in (256, True, '4'):
            with self.subTest(unit=repr(bad)):
                with self.assertRaisesRegex(ValueError,
                                            'Unit addresses must be integers in 0\\.\\.255'):
                    NetworkDiagnostics(_StubClient([])).diagnose(NETWORK, units=[bad])
        client = _StubClient([_xml([(4, 'KEYE1')])])
        with self.assertRaisesRegex(DiagnosticsError,
                                    'Selected units are not in the network database: 5'):
            NetworkDiagnostics(client).diagnose(NETWORK, units=[5])
        self.assertEqual(client.sent, [f'DBGETXML {NETWORK}'])


if __name__ == '__main__':
    unittest.main()
