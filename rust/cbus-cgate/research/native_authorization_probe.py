"""Capture bounded C-Gate 3.4 ACCESS role probes from an owned loopback child.

Requires the pinned extracted vendor directory and an explicit Java 11 binary.
The LocalCGate harness owns all ports, creates a disposable work directory and
stops the child before removing it. No project or C-Bus endpoint is attached.
Only response summaries and hashes are written; generated credentials stay in
the temporary work directory and in memory.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import secrets
import socket
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / 'toolkit-cli/research'))
from local_cgate import LocalCGate

LEVELS = ['None', 'Connect', 'Monitor', 'Operate', 'Admin', 'Program', 'Debug', 'Clipsal', 'Max']
COMMANDS = [
    'NOOP', 'APIVER', 'HELP *', 'PROJECT LIST', 'PROJECT USE TEST',
    'PROJECT NEW TEST', 'DBNEW', 'DBGET //TEST', 'DBGETXML //TEST',
    'DBSET //TEST/TagName Changed',
    'CONFIG GET clock.master', 'CONFIG SET clock.master no',
    'BROADCAST_EVENT SP probe', 'PP LOCK L //TEST/254',
    'EVENT', 'EVENT ON', 'ACCESS LIST', 'ACCESS SAVE probe.txt',
    'GET //TEST/254/56/1 Level', 'SHOW cgate', 'NET LIST',
    'NET PINGU //TEST/254', 'LIGHTING ON 254/56/1',
    'LIGHTING OFF 254/56/1', 'LIGHTING LABEL 254/56/1 test',
    'SCENE PLAY TEST', 'FILE DIR', 'FILE MKDIR probe',
    'CGL EXPORT', 'TELEPHONY RECALL_LAST_NUMBER_REQUEST 254/224 out',
    'TELEPHONY CLEAR_DIVERSION 254/224', 'AIRCON REFRESH 254/172 1',
    'AUDIO CURRENT_FEED 254/203 1', 'SECURITY STATUS_REQUEST 254/208 1',
    'EREPORT MESSAGE 254/206 1 1 n n n 0 0',
    'DALI SESSION LIST', 'SESSION_ID',
]

def command(stream, tag, body):
    stream.write(f'[{tag}] {body}\r\n'.encode())
    stream.flush()
    lines = []
    while True:
        raw = stream.readline()
        if not raw:
            raise EOFError((tag, body, lines))
        line = raw.decode(errors='replace').rstrip('\r\n')
        if line.startswith('#'):
            continue
        if not line.startswith(f'[{tag}] '):
            raise ValueError((tag, body, line))
        reply = line[len(tag) + 3:]
        lines.append(reply)
        if len(reply) >= 4 and reply[:3].isdigit() and reply[3] == ' ':
            return lines

def capture(vendor, java, output):
    oracle = LocalCGate(vendor, java=java)
    passwords = {level: secrets.token_hex(24) for level in LEVELS}
    result = {'format': 'native-cgate-authorization-probe-v1',
              'captured_at': datetime.now(timezone.utc).isoformat(),
              'oracle': {'product': 'Schneider Electric C-Gate', 'version': '3.4.0.2001',
                         'jar_sha256': hashlib.sha256((vendor/'cgate.jar').read_bytes()).hexdigest(),
                         'java_sha256': hashlib.sha256(java.read_bytes()).hexdigest(),
                         'help_sha256': hashlib.sha256((vendor/'help/cmds.txt').read_bytes()).hexdigest(),
                         'transport': 'owned native Java 11 child; six IPv4 loopback listeners; disposable TEST project; no C-Bus endpoint'},
              'capture_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'local_cgate_harness_sha256': hashlib.sha256(
                  (REPOSITORY / 'toolkit-cli/research/local_cgate.py').read_bytes()
              ).hexdigest(),
              'method': 'A disposable TEST project was created before probing. Each role used a fresh admitted command socket with an ACCESS user row; probes were sent on that socket after LOGIN. The probes share one disposable native service, so successful local commands can affect later status details. The DBSETXML probe sends deliberately invalid XML, preserving the project. Status 420 marks handler denial; another status only proves this invocation reached parsing/handler logic, not physical success or authorization after object resolution.',
              'roles': {}, 'session_transitions': {}}
    try:
        rows = ['interface 127.0.0.1 Clipsal'] + [f'user test-{level.lower()} {passwords[level]} {level}' for level in LEVELS]
        (oracle.work/'config/access.txt').write_text('\n'.join(rows)+'\n')
        with oracle:
            with socket.create_connection(('127.0.0.1', oracle.port), timeout=5) as sock:
                sock.settimeout(8)
                stream = sock.makefile('rwb', buffering=0)
                stream.readline()
                created = command(stream, 'bootstrap', 'PROJECT NEW TEST')[-1]
                if created != '200 OK.':
                    raise RuntimeError(f'Could not create disposable native project: {created}')
            for level in LEVELS:
                with socket.create_connection(('127.0.0.1', oracle.port), timeout=5) as sock:
                    sock.settimeout(8)
                    stream = sock.makefile('rwb', buffering=0)
                    greeting = stream.readline().decode().strip()
                    login = command(stream, 'login', f'LOGIN test-{level.lower()} {passwords[level]}')[-1]
                    query = command(stream, 'query', 'LOGIN')[-1]
                    responses = {}
                    for i, body in enumerate(COMMANDS):
                        reply = command(stream, f'probe{i}', body)
                        responses[body] = reply[-1]
                    responses['DBSETXML //TEST/Project/Description'] = command(
                        stream, 'document',
                        'DBSETXML //TEST/Project/Description << END\r\n'
                        'deliberately-invalid-xml\r\nEND',
                    )[-1]
                    logout = command(stream, 'logout', 'LOGOUT')[-1]
                    result['roles'][level] = {'greeting': greeting, 'login': login, 'query': query,
                                              'responses': responses, 'logout': logout}
            with socket.create_connection(('127.0.0.1', oracle.port), timeout=5) as sock:
                sock.settimeout(8)
                stream = sock.makefile('rwb', buffering=0)
                stream.readline()
                transitions = [
                    ('initial','LOGIN'),
                    ('admin',f'LOGIN test-admin {passwords["Admin"]}'),
                    ('after_admin','LOGIN'),
                    ('failed','LOGIN test-admin wrong'),
                    ('after_failed','LOGIN'),
                    ('none',f'LOGIN test-none {passwords["None"]}'),
                    ('after_none','LOGIN'),
                    ('logout','LOGOUT'),
                    ('after_logout','LOGIN'),
                ]
                result['session_transitions'] = {key: command(stream, key, body)[-1] for key, body in transitions}
    finally:
        result['oracle'].update({key: oracle.report.get(key) for key in ('listener_ownership_verified', 'cleanup_complete', 'process_exit_confirmed', 'work_removed', 'server_log_sha256')})
        # Native ACCESS LIST echoes user passwords. Retain the response shape
        # while replacing every per-run secret before committing a fixture.
        serialized = json.dumps(result, indent=2)
        for password in passwords.values():
            serialized = serialized.replace(password, '<redacted>')
        output.write_text(serialized + '\n')
    if not result['oracle']['cleanup_complete']:
        raise RuntimeError('Owned native process cleanup incomplete')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-dir', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = capture(args.vendor_dir.resolve(), args.java.resolve(), args.output.resolve())
    print(json.dumps({'output': str(args.output), 'cleanup': report['oracle']['cleanup_complete'],
                      'cases': len(COMMANDS), 'roles': len(report['roles'])}))
