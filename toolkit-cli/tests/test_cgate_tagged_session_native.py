"""Preserve the full tagged native envelope; replay is not fresh native capture."""
import json
from pathlib import Path
import re

import pytest

from cbus_toolkit.cgate import CGateClient, CGateError
from tests.test_cgate import peer

FIXTURE = Path(__file__).resolve().parents[1] / 'research/experiments/2026-09-28/cgate-tagged-session-native.json'
NATIVE = json.loads(FIXTURE.read_text())
CASES = NATIVE['cases']


def test_capture_keeps_every_client_prefix_separator_crlf_and_console_row():
    assert NATIVE['vendor_jar_sha256'] == '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630'
    assert NATIVE['scope']['all_six_listeners_owned_and_loopback']
    assert not NATIVE['scope']['projects_adopted']
    assert not NATIVE['scope']['physical_networks_opened']
    assert all(NATIVE['cleanup'].values())
    assert len(CASES) == 11
    for case in CASES:
        prefix = '[' + case['client_tag'] + '] '
        assert case['request'] == prefix + case['command'] + '\r\n'
        lines = case['response_lines']
        assert lines
        for index, line in enumerate(lines):
            assert line.startswith(prefix) and line.endswith('\r\n')
            payload = line[len(prefix):-2]
            assert re.fullmatch(r'[1-6][0-9]{2}[- ][^\r\n]+', payload)
            assert payload[3] == (' ' if index == len(lines) - 1 else '-')
        if case['command'] == 'SESSION_ID ALL':
            assert len(lines) == 3
            assert lines[0] == prefix + '300-sessionID=cmd1 origin=internal from=<timestamp:console> tag=Console\r\n'
            assert 'sessionID=<session:a> origin=/127.0.0.1:<port:a>' in lines[1]
            assert 'sessionID=<session:b> origin=/127.0.0.1:<port:b>' in lines[2]


@pytest.mark.parametrize('case', CASES, ids=lambda row: row['client_tag'])
def test_existing_python_client_consumes_all_native_tagged_lines(case):
    lines = case['response_lines']
    with peer([[line.encode('ascii') for line in lines]]) as (address, commands):
        with CGateClient(*address) as client:
            # Reproduce this exact numeric request tag, not a rewritten reply.
            client._sequence = int(case['client_tag']) - 1
            try:
                response = client.command(case['command'])
            except CGateError as error:
                response = error.response
            assert client.connected
            prefix = '[' + case['client_tag'] + '] '
            assert response.lines == tuple(line[len(prefix):-2] for line in lines)
            assert commands == [case['request'].encode('ascii')]


@pytest.mark.parametrize('index', range(3))
@pytest.mark.parametrize('alter', ['missing', 'wrong'])
def test_client_rejects_loss_or_change_of_any_all_response_tag(index, alter):
    case = next(case for case in CASES if case['command'] == 'SESSION_ID ALL')
    lines = list(case['response_lines'])
    prefix = '[' + case['client_tag'] + '] '
    lines[index] = ('' if alter == 'missing' else '[999] ') + lines[index][len(prefix):]
    with peer([[line.encode('ascii') for line in lines]]) as (address, commands):
        with CGateClient(*address) as client:
            client._sequence = int(case['client_tag']) - 1
            with pytest.raises(RuntimeError, match='unexpected or missing command ID'):
                client.command(case['command'])
            assert not client.connected


def test_native_tag_assignment_errors_preserve_existing_session_labels():
    by_tag = {case['client_tag']: case for case in CASES}
    for tag in ('503', '602'):
        assert by_tag[tag]['response_lines'] == [f'[{tag}] 200 OK.\r\n']
    assert by_tag['505']['response_lines'] == [
        '[505] 408 Operation failed: tag name has already been set\r\n'
    ]
    assert by_tag['506']['response_lines'] == [
        '[506] 400 Syntax Error: tag name not supplied\r\n'
    ]
    for tag in ('504', '603', '604'):
        lines = by_tag[tag]['response_lines']
        assert lines[1].endswith(' tag=native-a\r\n')
        assert lines[2].endswith(' tag=native-b\r\n')
        assert not any('replacement-a' in line for line in lines)
