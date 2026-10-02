"""Typed native documentation over independent literal C-Gate wire fixtures."""
import hashlib
import json
from unittest.mock import patch

import pytest

from cbus_toolkit.cli import main
from cbus_toolkit import native_project_documentation as live
from tests.test_cgate import peer


XML = (
    '<Installation><Project><TagName>Database Documentation</TagName>'
    '<Network><Address>254</Address><TagName>Local</TagName>'
    '<Interface><InterfaceType>CNI</InterfaceType><InterfaceAddress>127.0.0.1:1</InterfaceAddress></Interface>'
    '<Application><Address>56</Address><TagName>Lighting</TagName>'
    '<Group><Address>1</Address><TagName>Garage</TagName>'
    '<Level Value="128"><Address>7</Address><TagName>Half</TagName></Level></Group></Application>'
    '<Unit><Address>5</Address><TagName>Clock</TagName><UnitType>CLK2</UnitType>'
    '<FirmwareVersion>1.0</FirmwareVersion><UnitName>Synthetic clock</UnitName>'
    '<SerialNumber>1234.5</SerialNumber><Description>A&lt;B&gt;</Description>'
    '<PP Name="Application" Value="56 255"/><PP Name="ClockGenEnable" Value="1"/>'
    '<PP Name="Burden" Value="0"/></Unit></Network>'
    '<Network><Address>1</Address><TagName>Remote</TagName></Network>'
    '<Address>DOCNET</Address></Project></Installation>'
)


def wire(xml=XML, terminal=b'[1] 344 End XML snippet\r\n'):
    return b'[1] 343-Begin XML snippet\r\n[1] 347-' + xml.encode() + b'\r\n' + terminal


def call(capsys, *arguments):
    result = main(['cgate', *map(str, arguments)])
    captured = capsys.readouterr()
    return result, json.loads(captured.out or captured.err)


def test_complete_snapshot_identity_body_encoding_and_selection(tmp_path, capsys):
    for selected, addresses in [(None, [1, 254]), (254, [254])]:
        output = tmp_path / ('all.html' if selected is None else 'local.html')
        with peer([[wire()]]) as ((host, port), sent):
            args = ['--host', host, '--port', port, 'database-document',
                    '--project', '//docnet', '--output', output, '--generated-at', '2026-10-02T09:30']
            if selected is not None:
                args += ['--network', selected]
            code, value = call(capsys, *args)
        assert code == 0, value
        assert sent == [b'[1] DBGETXML //docnet\r\n']
        assert value['source_snapshot'] == {
            'project': '//docnet', 'command': 'DBGETXML //docnet', 'requests': 1,
            'completion_code': 344, 'sha256': hashlib.sha256(XML.encode()).hexdigest(),
            'bytes': len(XML.encode()),
        }
        assert value['networks'] == addresses
        assert value['project']['name'] == 'Database Documentation'
        assert value['units'] == [{'network': 254, 'unit': 5, 'unit_type': 'CLK2',
                                   'documentor': 'TClockDocumentor', 'status': 'recovered'}]
        raw = output.read_bytes()
        assert raw.startswith(b'\xef\xbb\xbf<html>\r\n') and raw.endswith(b'</html>\r\n')
        assert b'\n' not in raw.replace(b'\r\n', b'')
        assert b'Generated on: 02 Oct 2026 09:30<br />\r\n' in raw
        assert (
            'Unit Address: 5<br />\r\nTagname: Clock<br />\r\nPart name: Synthetic clock<br />\r\n'
            'Application: <a href="#254_56">Lighting</a><br />\r\n'
            'Secondary Application: <Unused><br />\r\nSerial Number: 000012340005<br />\r\n'
            'Firmware Version: 1.0<br />\r\nNotes: A&#60;B&#62;<br />\r\n'
            'Unit clock is enabled<br />\r\n<br />\r\n'
        ).encode() in raw
        assert b'name="254_56_1_7">Half</a>' in raw
        assert value['sha256'] == hashlib.sha256(raw).hexdigest()
        assert value['output_complete'] and not value['native_database_mutated']
        assert not value['physical_programming_loaded'] and not value['project_save_requested']
        assert not value['network_open_requested']
        assert value['parity']['original_toolkit_executed'] is False


@pytest.mark.parametrize('change,extra,error', [
    (lambda xml: xml.replace('<Address>DOCNET</Address>', '<Address>OTHER</Address>'), [], 'Project.Address'),
    (lambda xml: xml, ['--network', '2'], 'absent'),
    (lambda xml: xml.replace('<Group><Address>', '<NetVar><Address>').replace('</Group>', '</NetVar>'), [], 'NetVar'),
    (lambda xml: xml.replace('<Address>DOCNET</Address>', '<Address>DOCNET</Address><Address>DOCNET</Address>'), [], 'exactly one'),
])
def test_wrong_or_unsupported_snapshot_never_creates_output(change, extra, error, tmp_path, capsys):
    output = tmp_path / 'never.html'
    with peer([[wire(change(XML))]]) as ((host, port), sent):
        code, value = call(capsys, '--host', host, '--port', port, 'database-document',
                           '--project', '//DOCNET', '--output', output, *extra)
    assert code == 1 and error in value['error']
    assert sent == [b'[1] DBGETXML //DOCNET\r\n'] and not output.exists()


@pytest.mark.parametrize('terminal', [b'', b'[1] 200 OK.\r\n', b'[1] 408 Missing.\r\n'])
def test_missing_or_failed_xml_completion_does_not_write_or_retry(terminal, tmp_path, capsys):
    output = tmp_path / 'never.html'
    with peer([[wire(terminal=terminal)]]) as ((host, port), sent):
        code, _value = call(capsys, '--host', host, '--port', port, 'database-document',
                            '--project', '//DOCNET', '--output', output)
    assert code == 1 and sent == [b'[1] DBGETXML //DOCNET\r\n'] and not output.exists()


@pytest.mark.parametrize('payload', [
    b'[1] 347-' + XML.encode() + b'\r\n[1] 344 End XML snippet\r\n',
    b'[1] 123-Unrelated continuation\r\n[1] 347-' + XML.encode() + b'\r\n[1] 344 End XML snippet\r\n',
    wire(terminal=b'[1] 344 Arbitrary terminal\r\n'),
    wire().replace(b'[1] 347-', b'[1] 346-'),
    wire().replace(b'[1] 347-', b'[1] 343-'),
])
def test_malformed_xml_frame_is_atomic_and_not_retried(payload, tmp_path, capsys):
    output = tmp_path / 'never.html'
    with peer([[payload]]) as ((host, port), sent):
        code, result = call(capsys, '--host', host, '--port', port, 'database-document',
                            '--project', '//DOCNET', '--output', output)
    assert code == 1 and 'framing' in result['error']
    assert sent == [b'[1] DBGETXML //DOCNET\r\n'] and not output.exists()


@pytest.mark.parametrize('extra', [
    ['--project', '//DOCNET/254'], ['--project', '//TOOLONG99'],
    ['--project', '//DOCNET', '--generated-at', 'never'],
])
def test_invalid_preconditions_fail_before_connection(extra, tmp_path, capsys):
    output = tmp_path / 'never.html'
    prefix = ['--host', '127.0.0.1']
    with patch('socket.create_connection', side_effect=AssertionError('No connection')):
        code, _value = call(capsys, *prefix, 'database-document', '--output', output, *extra)
    assert code == 1 and not output.exists()


@pytest.mark.parametrize('symlink', [False, True])
def test_existing_file_or_dangling_link_is_preserved_before_connection(symlink, tmp_path, capsys):
    output = tmp_path / 'existing.html'
    if symlink:
        output.symlink_to(tmp_path / 'absent')
    else:
        output.write_bytes(b'keep')
    with patch('socket.create_connection', side_effect=AssertionError('No connection')):
        code, value = call(capsys, '--host', '127.0.0.1', 'database-document',
                           '--project', '//DOCNET', '--output', output)
    assert code == 1 and 'already exists' in value['error']
    assert output.is_symlink() if symlink else output.read_bytes() == b'keep'


def test_output_race_and_failed_flush_preserve_exclusive_publication(tmp_path, capsys):
    output = tmp_path / 'race.html'
    original = live._write_new

    def racing_writer(path, payload):
        path.write_bytes(b'competing writer')
        return original(path, payload)

    for fault, filename in [(racing_writer, 'race.html'), (None, 'flush.html')]:
        output = tmp_path / filename
        with peer([[wire()]]) as ((host, port), sent):
            context = (patch.object(live, '_write_new', side_effect=fault) if fault else
                       patch('cbus_toolkit.project_documentation.os.fsync', side_effect=OSError('flush failed')))
            with context:
                code, _value = call(capsys, '--host', host, '--port', port, 'database-document',
                                    '--project', '//DOCNET', '--output', output)
        assert code == 1 and sent == [b'[1] DBGETXML //DOCNET\r\n']
        if fault:
            assert output.read_bytes() == b'competing writer'
        else:
            assert not output.exists()


def test_long_native_xml_line_is_admitted_by_this_read_only_workflow(tmp_path, capsys):
    xml = XML.replace('A&lt;B&gt;', 'X' * (1024 * 1024 + 100))
    output = tmp_path / 'large.html'
    with peer([[wire(xml)]]) as ((host, port), sent):
        code, value = call(capsys, '--host', host, '--port', port, 'database-document',
                           '--project', '//DOCNET', '--output', output)
    assert code == 0, value
    assert sent == [b'[1] DBGETXML //DOCNET\r\n']
    assert value['source_snapshot']['sha256'] == hashlib.sha256(xml.encode()).hexdigest()
    assert output.stat().st_size > 1024 * 1024
