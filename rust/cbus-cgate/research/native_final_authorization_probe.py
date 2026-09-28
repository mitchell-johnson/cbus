"""Probe remaining C-Gate 3.4 ACCESS entries on owned loopback children.

Each regular invocation gets a fresh command socket, so QUIT, LOGOUT, TAG,
SHUTDOWN (without CONFIRM), and here-document grammar cannot influence another
probe. ACCESS LOAD gets a separate disposable native child for every role.
Object paths refer only to the absent MISSING project; no PCI is configured.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import socket

import native_admin_authorization_probe as base


COMMANDS = {
    '#': '# role-probe',
    '//': '// role-probe',
    'ACCESS_CONTROL CLOSE': 'ACCESS_CONTROL CLOSE //MISSING/254/213 1 2',
    'ACCESS_CONTROL LOCK': 'ACCESS_CONTROL LOCK //MISSING/254/213 1 2',
    'AIRCON': 'AIRCON',
    'AUDIO': 'AUDIO',
    'CGL': 'CGL',
    'CLOCK': 'CLOCK',
    'CONFIG': 'CONFIG',
    'CONFIRM': 'CONFIRM',
    'ENABLE': 'ENABLE',
    'EREPORT': 'EREPORT',
    'FILE UPLOAD': 'FILE UPLOAD authorization-probe.bin',
    'LIGHTING': 'LIGHTING',
    'LOGIN': 'LOGIN',
    'LOGOUT': 'LOGOUT',
    'MEASUREMENT': 'MEASUREMENT',
    'MEDIATRANSPORT': 'MEDIATRANSPORT',
    'NET': 'NET',
    'NETWORK': 'NETWORK',
    'PORT': 'PORT',
    'PROJECT': 'PROJECT',
    'QUIT': 'QUIT',
    'SECURITY': 'SECURITY',
    'SESSION_ID TAG': 'SESSION_ID TAG authorization-probe',
    'SHORTMESSAGE': 'SHORTMESSAGE',
    'SHUTDOWN': 'SHUTDOWN',
    'TELEPHONY': 'TELEPHONY',
    'TEMPERATURE': 'TEMPERATURE',
    'TEST_SPAM': 'TEST_SPAM',
    'TEST_SPAM EREPORT': 'TEST_SPAM EREPORT //MISSING/254 60000 1',
    'TEST_SPAM LIGHTING': 'TEST_SPAM LIGHTING //MISSING/254 60000 1',
    'TOPOLOGY': 'TOPOLOGY',
    'TRIGGER': 'TRIGGER',
    'APPLICATIONS': 'APPLICATIONS',
    'CALCULATOR': 'CALCULATOR',
    'CMQTT CAPABILITIES': 'CMQTT CAPABILITIES',
    'CMQTT LABELS': 'CMQTT LABELS //MISSING/254/p/1',
    'IDENTIFY': 'IDENTIFY',
    'REPOSITORY': 'REPOSITORY',
    'TRANSFORM': 'TRANSFORM',
    'UNIT READMEM': 'UNIT READMEM //MISSING/254/p/1 0 1',
    'UNIT IDENTIFY': 'UNIT IDENTIFY //MISSING/254/p/1',
}


def role_rows(level, password):
    return f'interface 127.0.0.1 Clipsal\nuser final-{level.lower()} {password} {level}\n'


def one_command(oracle, level, password, path, body):
    with socket.create_connection(('127.0.0.1', oracle.port), timeout=5) as sock:
        sock.settimeout(8)
        stream = sock.makefile('rwb', buffering=0)
        greeting = stream.readline().decode(errors='replace').strip()
        login = base.command(stream, 'login', f'LOGIN final-{level.lower()} {password}')[-1]
        query = base.command(stream, 'query', 'LOGIN')[-1]
        if login != f'211 Access level set to: {level}' or query != f'210 Access level: {level}':
            raise RuntimeError(f'Native role setup failed for {path} at {level}: {login}, {query}')
        try:
            lines = base.command(stream, 'probe', body)
        except ValueError as error:
            # Native comment parsing strips the command id before answering.
            line = error.args[0][-1] if error.args and isinstance(error.args[0], tuple) else ''
            return {'greeting': greeting, 'login': login, 'query': query,
                    'unmatched_reply': base.summarize(line, oracle.work)}
        except (TimeoutError, EOFError) as error:
            return {'greeting': greeting, 'login': login, 'query': query,
                    'error': type(error).__name__}
        return {'greeting': greeting, 'login': login, 'query': query,
                'reply': base.summarize(lines[-1], oracle.work),
                'line_count': len(lines),
                'response_sha256': hashlib.sha256('\n'.join(lines).encode()).hexdigest()}


def capture(vendor, java, output):
    report = {
        'format': 'native-cgate-final-authorization-v1',
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'oracle': {'product': 'Schneider Electric C-Gate', 'version': '3.4.0.2001',
                   'jar_sha256': hashlib.sha256((vendor / 'cgate.jar').read_bytes()).hexdigest(),
                   'java_sha256': hashlib.sha256(java.read_bytes()).hexdigest(),
                   'help_sha256': hashlib.sha256((vendor / 'help/cmds.txt').read_bytes()).hexdigest(),
                   'transport': 'owned Java 11 children; six IPv4 loopback listeners each; no C-Bus endpoint'},
        'capture_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'capture_engine_sha256': hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest(),
        'local_cgate_harness_sha256': hashlib.sha256(
            (base.REPOSITORY / 'toolkit-cli/research/local_cgate.py').read_bytes()).hexdigest(),
        'method': ('Each exact invocation uses a fresh role socket. ACCESS LOAD uses one '
                   'separate owned child per role. SHUTDOWN is never followed by CONFIRM. '
                   'MISSING has no project or physical endpoint. A 420/non-420 gradient '
                   'establishes only the invoked entry floor, not later object or PCI policy.'),
        'invocations': COMMANDS | {'ACCESS LOAD': 'ACCESS LOAD authorization-probe-missing'},
        'roles': {},
        'access_load_children': {},
    }
    passwords = {level: secrets.token_hex(24) for level in base.LEVELS}
    oracle = base.LocalCGate(vendor, java=java)
    (oracle.work / 'config/access.txt').write_text(
        'interface 127.0.0.1 Clipsal\n' + ''.join(
            f'user final-{level.lower()} {passwords[level]} {level}\n'
            for level in base.LEVELS
        ))
    try:
        with oracle:
            for level in base.LEVELS:
                report['roles'][level] = {
                    path: one_command(oracle, level, passwords[level], path, body)
                    for path, body in COMMANDS.items()
                }
    finally:
        report['oracle']['regular_child'] = {
            key: oracle.report.get(key) for key in (
                'listener_ownership_verified', 'cleanup_complete',
                'process_exit_confirmed', 'work_removed', 'server_log_sha256')
        }

    for level in base.LEVELS:
        child = base.LocalCGate(vendor, java=java)
        (child.work / 'config/access.txt').write_text(role_rows(level, passwords[level]))
        try:
            with child:
                report['access_load_children'][level] = one_command(
                    child, level, passwords[level], 'ACCESS LOAD',
                    report['invocations']['ACCESS LOAD'])
        finally:
            report['access_load_children'][level]['oracle'] = {
                key: child.report.get(key) for key in (
                    'listener_ownership_verified', 'cleanup_complete',
                    'process_exit_confirmed', 'work_removed', 'server_log_sha256')
            }
    raw_roles = report.pop('roles')
    levels = base.LEVELS
    floor_paths = []
    nonfloor_paths = []
    for path in report['invocations']:
        rows = [report['access_load_children'][level] if path == 'ACCESS LOAD'
                else raw_roles[level][path] for level in levels]
        denied = [row.get('reply') == '420 Access denied.' for row in rows]
        first_admitted = next((i for i, value in enumerate(denied) if not value), None)
        if first_admitted and denied == [True] * first_admitted + [False] * (9 - first_admitted):
            floor_paths.append(path)
        else:
            nonfloor_paths.append(path)
    if len(floor_paths) != 33 or len(nonfloor_paths) != 11:
        raise RuntimeError('Native handler-entry classifications changed')
    invocations = report.pop('invocations')
    report['commands'] = [invocations[path] for path in floor_paths]
    report['nonfloor_commands'] = {path: invocations[path] for path in nonfloor_paths}
    report['nonfloor_roles'] = {
        level: {path: raw_roles[level][path] for path in nonfloor_paths}
        for level in levels
    }
    report['roles'] = {}
    for level in levels:
        records = raw_roles[level]
        first = records['AIRCON']
        report['roles'][level] = {
            'greeting': first['greeting'], 'login': first['login'], 'query': first['query'],
            'responses': {
                invocations[path]: (report['access_load_children'][level] if path == 'ACCESS LOAD'
                                    else records[path])['reply']
                for path in floor_paths
            },
        }
    report['oracle'].update(report['oracle']['regular_child'])
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-dir', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = capture(args.vendor_dir.resolve(), args.java.resolve(), args.output.resolve())
    print(json.dumps({'output': str(args.output), 'regular_cleanup': result['oracle']['regular_child']['cleanup_complete'],
                      'access_load_cleanup': all(c['oracle']['cleanup_complete'] for c in result['access_load_children'].values()),
                      'paths': len(result['commands']) + len(result['nonfloor_commands']), 'roles': len(result['roles'])}))
