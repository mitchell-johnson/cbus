"""CLI timeout defaults for network-wide eDLT reads, without a live endpoint."""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.cli import build_parser, run


class Connection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def command(self, command):
        assert command == "NOOP"
        return CGateResponse(("200 OK.",), "200 OK.", 200)


@pytest.mark.parametrize(('argv', 'expected'), [
    (['edlt-labels', '--network', '//TEST/254'], 300.0),
    (['edlt-label-audit', '//TEST/254'], 300.0),
    (['edlt-labels', '//TEST/254/p/5'], 10.0),
    (['exec', 'NOOP'], 10.0),
    (['--timeout', '15', 'edlt-labels', '--network', '//TEST/254'], 15.0),
    (['--timeout', '20', 'edlt-label-audit', '//TEST/254'], 20.0),
    (['--timeout', '7', 'edlt-labels', '//TEST/254/p/5'], 7.0),
    (['--timeout', '6', 'exec', 'NOOP'], 6.0),
])
def test_cgate_timeout_selection_reaches_the_connection(argv, expected):
    args = build_parser().parse_args(['cgate', *argv])
    assert args.timeout == (expected if '--timeout' in argv else 10.0)
    assert args.cgate_timeout_explicit is ('--timeout' in argv)
    with patch('cbus_toolkit.cgate.CGateClient', return_value=Connection()) as client, \
            patch('cbus_toolkit.cmqtt.edlt_label_inventory', return_value={'complete': True}), \
            patch('cbus_toolkit.cmqtt.edlt_labels', return_value={'complete': True}), \
            patch('cbus_toolkit.edlt_label_audit.capture_label_audit',
                  return_value={'accepted': True}):
        _, status = run(args)
    assert status == 0
    assert client.call_args.kwargs['timeout'] == expected
    if args.action == 'edlt-labels':
        assert client.call_args.kwargs['max_line_bytes'] > 4 * 1024 * 1024
    assert args.timeout == (expected if '--timeout' in argv else 10.0)


def test_nonpositive_explicit_timeout_is_rejected_before_connection():
    parser = build_parser()
    for value in ('0', '-1'):
        with pytest.raises(SystemExit):
            parser.parse_args(['cgate', '--timeout', value,
                               'edlt-labels', '--network', '//TEST/254'])


@pytest.mark.parametrize(('argv', 'expected', 'refresh_expected'), [
    (['serials', 'refresh', '//TEST/254'], 300.0, True),
    (['serials', 'refresh', '//TEST/254', '--unit', '5'], 300.0, True),
    (['serials', 'cached', '//TEST/254'], 10.0, False),
    (['serials', 'populate', '//TEST/254', '--refresh', '--dry-run'], 300.0, True),
    (['serials', 'populate', '//TEST/254', '--refresh'], 300.0, True),
    (['serials', 'populate', '//TEST/254'], 10.0, False),
    (['--timeout', '8', 'serials', 'refresh', '//TEST/254'], 8.0, True),
    (['--timeout', '9', 'serials', 'populate', '//TEST/254', '--refresh'], 9.0, True),
])
def test_serial_refresh_timeout_covers_whole_network_scan(argv, expected, refresh_expected):
    args = build_parser().parse_args(['cgate', *argv])
    parsed_timeout = args.timeout
    inventory = Mock(complete=False)
    inventory.as_dict.return_value = {'complete': False}
    with patch('cbus_toolkit.cgate.CGateClient', return_value=Connection()) as client, \
            patch('cbus_toolkit.serials.NativeSerials.refresh', return_value=inventory) as refresh, \
            patch('cbus_toolkit.serials.NativeSerials.cached', return_value=inventory) as cached:
        _, status = run(args)
    assert status == 1
    assert client.call_args.kwargs['timeout'] == expected
    assert args.timeout == parsed_timeout
    assert refresh.call_count == int(refresh_expected)
    assert cached.call_count == int(not refresh_expected)
