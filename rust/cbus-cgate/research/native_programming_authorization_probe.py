"""Probe C-Gate 3.4 programming and queue command-role boundaries on an owned loopback child.

The selected commands use a disposable TEST project, missing object paths, or
local query/help forms. No C-Bus interface, broker, site project, or external
network address is configured. Response summaries and source hashes are the
only retained output; random ACCESS credentials stay in the temporary child.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import socket
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / 'toolkit-cli/research'))
from local_cgate import LocalCGate

LEVELS = ['None', 'Connect', 'Monitor', 'Operate', 'Admin', 'Program', 'Debug', 'Clipsal', 'Max']

# These are invocation probes, not proof of physical success. MISSING has no
# project or network, so controls cannot reach a real interface. Successful
# local mutation is limited to the disposable child work directory.
COMMANDS = [
    'PP UNLOCK missing',
    'PP CANCEL_LOCK missing',
    'PP START missing missing',
    'PP END missing',
    'PP UNITS',
    'PP NEW missing MISSING 1.2.3',
    'PP DEBUG mem missing 0',
    'PP LOAD missing /db//MISSING/254/p/1',
    'PP SAVE missing /db//MISSING/254/p/1',
    'PP SAVE_TO_SOURCE missing',
    'PP SET missing UnitName Probe',
    'PP GET missing UnitName',
    'PP INFO missing',
    'PP LIST_LOCK',
    'PP LOAD_FROM_FILE missing missing.xml',
    'PP GET_UNIT_SPEC MISSING.xml',
    'PP GET_UNIT_CATALOG',
    'PP RELOAD_CATALOG',
    'PP CATALOG_INFO MISSING',
    'PP LIST_CATALOG_NUMBERS MISSING 1.2.3',
    'PP GET_RAW_DATA missing 0 8',
    'PP SET_RAW_DATA missing 0 00',
    'PP COPY missing /db//MISSING/254/p/1 /db//MISSING/254/p/2',
    'PP QUICKGET //MISSING/254/p/1 UnitName',
    'PP RESET_TO_DEFAULTS missing',
    'PP PATCH_VERSION //MISSING/254/p/1',
    'PP WRITE_PATCH //MISSING/254/p/1 01',
    'PROGRAMMER CREATE missing Owned local',
    'PROGRAMMER LIST',
    'PROGRAMMER STATUS missing',
    'PROGRAMMER DELETE missing',
    'PROGRAMMER TRIGGER missing START',
    'PROGRAMMER TEST missing payload',
    'PROGRAMMER ADD_INSTRUCTION missing PP_END absent',
    'PROGRAMMER CANCEL_INSTRUCTION missing absent',
    'DEPLOY_QUEUE ADD missing',
    'DEPLOY_QUEUE LIST',
    'DEPLOY_QUEUE DELETE missing',
    'DEPLOY_QUEUE DELETE_ALL',
    'DEPLOY_QUEUE RETRY missing',
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
        prefix = f'[{tag}] '
        if not line.startswith(prefix):
            raise ValueError((tag, body, line))
        reply = line[len(prefix):]
        lines.append(reply)
        if len(reply) >= 4 and reply[:3].isdigit() and reply[3] == ' ':
            return lines


def summarize(reply, work):
    """Keep status semantics while removing host-local path and interface data."""
    reply = reply.replace(str(work), '<owned-work>')
    reply = re.sub(r'\baddress=\d{1,3}(?:\.\d{1,3}){3}\b',
                   'address=<host-interface>', reply)
    reply = re.sub(r'\bport=\S+ status=', 'port=<host-port> status=', reply)
    reply = re.sub(r'origin=/127\.0\.0\.1:\d+',
                   'origin=/127.0.0.1:<ephemeral>', reply)
    return reply


def capture(vendor, java, output):
    oracle = LocalCGate(vendor, java=java)
    passwords = {level: secrets.token_hex(24) for level in LEVELS}
    report = {
        'format': 'native-cgate-programming-authorization-v1',
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'oracle': {
            'product': 'Schneider Electric C-Gate',
            'version': '3.4.0.2001',
            'jar_sha256': hashlib.sha256((vendor / 'cgate.jar').read_bytes()).hexdigest(),
            'java_sha256': hashlib.sha256(java.read_bytes()).hexdigest(),
            'help_sha256': hashlib.sha256((vendor / 'help/cmds.txt').read_bytes()).hexdigest(),
            'transport': 'owned native Java 11 child; six IPv4 loopback listeners; disposable TEST project; no C-Bus endpoint',
        },
        'capture_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'local_cgate_harness_sha256': hashlib.sha256(
            (REPOSITORY / 'toolkit-cli/research/local_cgate.py').read_bytes()
        ).hexdigest(),
        'method': 'Each role used a fresh admitted command socket, a generated ACCESS user and LOGIN. Commands used a disposable TEST project or absent MISSING objects. A 420 marks denial; a non-420 proves only that this invocation reached a later parser/handler stage. No physical success is inferred. The rows share one disposable service, so local status details may depend on earlier probes.',
        'commands': COMMANDS,
        'roles': {},
    }
    try:
        rows = ['interface 127.0.0.1 Clipsal'] + [
            f'user matrix-{level.lower()} {passwords[level]} {level}' for level in LEVELS
        ]
        (oracle.work / 'config/access.txt').write_text('\n'.join(rows) + '\n')
        with oracle:
            with socket.create_connection(('127.0.0.1', oracle.port), timeout=5) as sock:
                sock.settimeout(10)
                stream = sock.makefile('rwb', buffering=0)
                stream.readline()
                created = command(stream, 'bootstrap', 'PROJECT NEW TEST')[-1]
                if created != '200 OK.':
                    raise RuntimeError(f'Could not create disposable native project: {created}')
            for level in LEVELS:
                with socket.create_connection(('127.0.0.1', oracle.port), timeout=5) as sock:
                    sock.settimeout(10)
                    stream = sock.makefile('rwb', buffering=0)
                    greeting = stream.readline().decode(errors='replace').strip()
                    login = command(stream, 'login', f'LOGIN matrix-{level.lower()} {passwords[level]}')[-1]
                    query = command(stream, 'query', 'LOGIN')[-1]
                    responses = {}
                    for i, body in enumerate(COMMANDS):
                        responses[body] = summarize(command(stream, f'p{i}', body)[-1], oracle.work)
                    report['roles'][level] = {
                        'greeting': greeting, 'login': login, 'query': query,
                        'responses': responses,
                    }
    finally:
        report['oracle'].update({key: oracle.report.get(key) for key in (
            'listener_ownership_verified', 'cleanup_complete',
            'process_exit_confirmed', 'work_removed', 'server_log_sha256')})
        serialized = json.dumps(report, indent=2)
        for password in passwords.values():
            serialized = serialized.replace(password, '<redacted>')
        output.write_text(serialized + '\n')
    if not report['oracle']['cleanup_complete']:
        raise RuntimeError('Owned native process cleanup incomplete')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-dir', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = capture(args.vendor_dir.resolve(), args.java.resolve(), args.output.resolve())
    print(json.dumps({
        'output': str(args.output),
        'cleanup': report['oracle']['cleanup_complete'],
        'cases': len(COMMANDS),
        'roles': len(report['roles']),
    }))
