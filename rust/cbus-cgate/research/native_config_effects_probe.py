"""Capture one bounded C-Gate 3.4 CONFIG restart effect on owned loopback children.

Only `command.show-time` is tested. The first child saves the global config;
the saved value alone is copied into a fresh owned child's startup config.
No existing daemon, project, C-Bus endpoint, or host configuration is used.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / 'toolkit-cli/research'))
from local_cgate import LocalCGate


def command(stream, tag, body):
    stream.write(f'[{tag}] {body}\r\n'.encode())
    stream.flush()
    rows = []
    while True:
        line = stream.readline().decode('utf-8', errors='replace').rstrip('\r\n')
        if not line:
            raise EOFError((tag, body, rows))
        if line.startswith('#'):
            continue
        rows.append(line)
        if line.startswith(f'[{tag}] ') and len(line) > len(tag) + 6 and line[len(tag) + 6] == ' ':
            return rows


def drain_events(sock):
    sock.settimeout(.2)
    data = bytearray()
    while True:
        try:
            chunk = sock.recv(8192)
        except socket.timeout:
            break
        if not chunk:
            break
        data.extend(chunk)
    return data.decode('utf-8', errors='replace').splitlines()


def socket_line(sock):
    data = bytearray()
    while len(data) < 512:
        char = sock.recv(1)
        if not char:
            raise EOFError('Native command listener closed before line ending')
        data.extend(char)
        if char == b'\n':
            return data.decode('utf-8', errors='replace').rstrip('\r\n')
    raise AssertionError('Native greeting/ack exceeded 512 bytes')


def time_events(lines, tag):
    result = []
    for line in lines:
        if ' 767 ' not in line:
            continue
        match = re.fullmatch(
            r'#e# ([0-9]{8}-[0-9]{6}\.[0-9]{3}) 767 cmd([0-9]+) - commandId=(.*?) time=([0-9]+)',
            line,
        )
        if match is None:
            raise AssertionError(f'Unexpected native command timing envelope: {line!r}')
        if match.group(3) == tag:
            result.append({
                'event_code': 767,
                'command_id': match.group(3),
                'time_ms': int(match.group(4)),
                'timestamp_shape': 'YYYYMMDD-HHMMSS.mmm',
                'session_id': 'cmd<owned-session>',
            })
    return result


def session(oracle, cases, *, require_saved=None):
    with oracle:
        with socket.create_connection(('127.0.0.1', oracle.port), timeout=15) as subscriber:
            subscriber.settimeout(15)
            greeting = socket_line(subscriber)
            if not greeting.startswith('201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)'):
                raise AssertionError(greeting)
            with socket.create_connection(('127.0.0.1', oracle.port), timeout=15) as producer:
                producer.settimeout(15)
                stream = producer.makefile('rwb', buffering=0)
                second_greeting = stream.readline().decode().rstrip('\r\n')
                if not second_greeting.startswith('201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001)'):
                    raise AssertionError(second_greeting)
                subscriber.sendall(b'[subscribe] EVENT e9s0c0\r\n')
                ack = socket_line(subscriber)
                if ack != '[subscribe] 200 OK.':
                    raise AssertionError(ack)
                drain_events(subscriber)
                result = []
                for tag, body, expected, expected_timing_events in cases:
                    rows = command(stream, tag, body)
                    if rows[-1] != f'[{tag}] {expected}':
                        raise AssertionError((body, rows))
                    event_rows = drain_events(subscriber)
                    timing_events = time_events(event_rows, tag)
                    if len(timing_events) != expected_timing_events:
                        raise AssertionError((body, timing_events, expected_timing_events))
                    result.append({
                        'command': body,
                        'response': rows,
                        'time_events': timing_events,
                    })
                if require_saved is not None:
                    config = (oracle.work / 'config/C-GateConfig.txt').read_text()
                    if f'command.show-time={require_saved}' not in config.splitlines():
                        raise AssertionError('Native CONFIG SAVE did not retain the selected startup key')
                return result


def configured_oracle(vendor, java, setting=None):
    oracle = LocalCGate(vendor, java=java)
    if setting is not None:
        # LocalCGate created this exclusive temporary directory. The only
        # extension is a known global boolean in its startup configuration.
        if setting not in ('yes', 'no'):
            raise ValueError('Only native yes/no startup values are admitted')
        with (oracle.work / 'config/C-GateConfig.txt').open('a') as config:
            config.write(f'command.show-time={setting}\n')
    return oracle


def capture(vendor, java, output):
    initial = configured_oracle(vendor, java)
    report = {
        'format': 'native-cgate-config-command-show-time-v1',
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'oracle': {
            'product': 'Schneider Electric C-Gate',
            'version': '3.4.0.2001',
            'jar_sha256': hashlib.sha256((vendor / 'cgate.jar').read_bytes()).hexdigest(),
            'java_sha256': hashlib.sha256(java.read_bytes()).hexdigest(),
            'transport': 'fresh owned Java 11 child per startup value; IPv4 loopback command/event listeners; no C-Bus endpoint',
        },
        'capture_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'local_cgate_harness_sha256': hashlib.sha256((REPOSITORY / 'toolkit-cli/research/local_cgate.py').read_bytes()).hexdigest(),
        'method': 'The first child changed command.show-time from no to yes, saved global config, and observed timing events before restart. Its saved key was replayed into a fresh owned child. That child changed yes to no without restart. A third fresh child started with no. Event timestamps and owned session numbers are normalized; status lines, event code, command IDs and nonnegative integer millisecond shape are retained.',
        'cases': {},
    }
    try:
        report['cases']['default_then_set_yes'] = session(initial, [
            ('before', 'NOOP', '200 OK.', 0),
            ('set-yes', 'CONFIG SET command.show-time yes', '200 OK.', 0),
            ('read-yes', 'CONFIG GET command.show-time', '303 command.show-time=yes', 0),
            ('after-set', 'NOOP', '200 OK.', 0),
            ('save', 'CONFIG SAVE global', '200 OK.', 0),
        ], require_saved='yes')
        # The harness removes its working directory on exit. Only the verified
        # saved boolean above is replayed, keeping the next child on fresh
        # owned loopback ports.
        enabled = configured_oracle(vendor, java, 'yes')
        report['cases']['startup_yes_then_set_no'] = session(enabled, [
            ('after-restart', 'NOOP', '200 OK.', 1),
            ('invalid', 'CONFIG SET no-such-parameter yes', '408 Operation failed: config parameter not found', 1),
            ('set-no', 'CONFIG SET command.show-time no', '200 OK.', 1),
            ('read-no', 'CONFIG GET command.show-time', '303 command.show-time=no', 1),
            ('before-second-restart', 'NOOP', '200 OK.', 1),
        ])
        disabled = configured_oracle(vendor, java, 'no')
        report['cases']['startup_no'] = session(disabled, [
            ('after-second-restart', 'NOOP', '200 OK.', 0),
        ])
        for name, child in [('default', initial), ('yes', enabled), ('no', disabled)]:
            report['oracle'][name + '_cleanup'] = {
                key: child.report[key] for key in (
                    'listener_ownership_verified', 'cleanup_complete',
                    'process_exit_confirmed', 'work_removed', 'server_log_sha256',
                )
            }
    finally:
        # Each `session` context closes its child on success and failure.
        # Do not save a report if any owned child failed to close.
        for child in (initial, locals().get('enabled'), locals().get('disabled')):
            if child is not None and not child.closed:
                child.close()
    if not all(report['oracle'][name + '_cleanup']['cleanup_complete'] for name in ('default', 'yes', 'no')):
        raise RuntimeError('Owned native cleanup incomplete')
    output.write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-dir', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    evidence = capture(args.vendor_dir.resolve(), args.java.resolve(), args.output.resolve())
    print(json.dumps({'output': str(args.output), 'cases': sum(map(len, evidence['cases'].values())), 'cleanup': True}))
