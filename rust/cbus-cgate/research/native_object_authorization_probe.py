#!/usr/bin/env python3
"""Capture native C-Gate 3.4 per-object parameter and method access levels.

One owned build-2001 loopback child opens a disposable project whose network
points at the synthetic PCI in ``toolkit-cli/research/unit_diagnostics_fixture``
(units 4, 5, 16 and 17 answer on the simulated bus). Sessions LOGIN as random
per-level users and issue a representative matrix: for each object class a
writable parameter, a read-only (Max-write) parameter or restricted read, and
a method, at the role just below the source-derived level and at that level.

No C-Bus interface, broker or external address is used. Credentials are
redacted, generated OIDs are normalized and the simulator port is removed.

    CBUS_LOCAL_CGATE_VENDOR=... CBUS_CGATE_JAVA=... python \\
        rust/cbus-cgate/research/native_object_authorization_probe.py --output <json>
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
import time

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / 'toolkit-cli/research'))
sys.path.insert(0, str(REPOSITORY / 'toolkit-cli/src'))
from local_cgate import LocalCGate  # noqa: E402
import unit_diagnostics_fixture as fixture  # noqa: E402

LEVELS = ['None', 'Connect', 'Monitor', 'Operate', 'Admin', 'Program', 'Debug', 'Clipsal', 'Max']
PROJECT = 'AUTHOBJ'
NET = f'//{PROJECT}/254'

# (object class, kind, command, levels probed). The first level is below the
# source-derived requirement (or the only grantable level for Max rows).
MATRIX = [
    ('cgate', 'read', 'GET cgate KCount', ['Debug', 'Clipsal']),
    ('cgate', 'write', 'SET cgate EventLevel 5', ['Monitor', 'Operate']),
    ('cgate', 'read-only', 'SET cgate Version 1', ['Clipsal']),
    ('project', 'read', f'GET //{PROJECT} Networks', ['Connect', 'Monitor']),
    ('project', 'read-only', f'SET //{PROJECT} Networks 1', ['Clipsal']),
    ('network', 'read', f'GET {NET} TxQ', ['Admin', 'Program']),
    ('network', 'write', f'SET {NET} AutoSync false', ['Admin', 'Program']),
    ('network', 'write', f'SET {NET} Retries 0', ['Monitor', 'Operate']),
    ('network', 'read-only', f'SET {NET} Type 1', ['Clipsal']),
    ('network', 'method', f'DO {NET} Sync', ['Operate', 'Admin']),
    ('application', 'write', f'SET {NET}/56 Name Probe', ['Monitor', 'Operate']),
    ('application', 'read-only', f'SET {NET}/56 Address 57', ['Clipsal']),
    ('application', 'method', f'DO {NET}/56 AllOff', ['Monitor', 'Operate']),
    ('group', 'read', f'GET {NET}/56/1 Level', ['Connect', 'Monitor']),
    ('group', 'write', f'SET {NET}/56/1 Level 0', ['Monitor', 'Operate']),
    ('group', 'read-only', f'SET {NET}/56/1 Units 1', ['Clipsal']),
    ('group', 'method', f'DO {NET}/56/1 Off', ['Monitor', 'Operate']),
    ('unit', 'read', f'GET {NET}/p/4 NetVoltage', ['Monitor', 'Operate']),
    ('unit', 'read-only', f'SET {NET}/p/4 Serial 1', ['Clipsal']),
    ('unit', 'write', f'SET {NET}/p/4 LearnEnable false', ['Admin', 'Program']),
    ('unit', 'method', f'DO {NET}/p/4 PSync', ['Operate', 'Admin']),
    ('unit', 'write', f'SET {NET}/p/5 Address 40', ['Admin', 'Program']),
]
NOW = re.compile(r'now=\d+')
OID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


class Session:
    """One command socket; every read is bounded by the socket timeout."""

    def __init__(self, port):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.sock.settimeout(20)
        self.stream = self.sock.makefile('rwb', buffering=0)
        self.greeting = self.stream.readline().decode(errors='replace').strip()
        self.count = 0

    def run(self, body):
        self.count += 1
        tag = f'o{self.count}'
        self.stream.write(f'[{tag}] {body}\r\n'.encode())
        lines = []
        try:
            while True:
                raw = self.stream.readline()
                if not raw:
                    return lines + ['<eof>']
                line = raw.decode(errors='replace').rstrip('\r\n')
                if not line.startswith(f'[{tag}] '):
                    continue
                reply = line[len(tag) + 3:]
                lines.append(reply)
                if len(reply) >= 4 and reply[:3].isdigit() and reply[3] == ' ':
                    return lines
        except (TimeoutError, socket.timeout):
            return lines + ['<timeout>']

    def close(self):
        self.stream.close()
        self.sock.close()


def sanitize(lines, passwords):
    out = []
    for line in lines:
        for value in passwords:
            line = line.replace(value, '<redacted>')
        out.append(NOW.sub('now=<millis>', OID.sub('<oid>', line)))
    return out


def capture(vendor, java):
    passwords = {level: secrets.token_hex(16) for level in LEVELS[1:8]}
    oracle = LocalCGate(vendor, java=java)
    (oracle.work / 'config/access.txt').write_text(
        'interface 127.0.0.1 Connect\n' + ''.join(
            f'user obj-{level.lower()} {password} {level}\n' for level, password in passwords.items()))
    result = {'access': ['interface 127.0.0.1 Connect'] + [
        f'user obj-{level.lower()} <redacted> {level}' for level in passwords], 'setup': [], 'matrix': [],
        'cleanup': []}
    sim = fixture.diagnostics_simulator()
    with sim.running('127.0.0.1', 0) as (_, sim_port):
        oracle.start()
        try:
            admin = Session(oracle.port)
            admin.run(f'LOGIN obj-clipsal {passwords["Clipsal"]}')
            for body in (f'PROJECT NEW {PROJECT}', f'PROJECT USE {PROJECT}',
                         f'DBCREATENET 254 Auth Cni 127.0.0.1:{sim_port}',
                         f'DBADDSAFE {NET} Application 56 Lighting', f'DBADDSAFE {NET}/56 Group 1 Probe'):
                result['setup'].append({'command': body.replace(str(sim_port), '<sim>'),
                                        'lines': sanitize(admin.run(body), passwords.values())})
            for address, unit_type, firmware in fixture.DATABASE_UNITS[:2]:
                for body in (f'DBADDSAFE {NET} Unit {address} U{address}',
                             f'DBSETSAFE {NET}/p/{address}/UnitType {unit_type}',
                             f'DBSETSAFE {NET}/p/{address}/FirmwareVersion {firmware}',
                             f'DBSETSAFE {NET}/p/{address}/UnitName U{address}'):
                    result['setup'].append({'command': body,
                                            'lines': sanitize(admin.run(body), passwords.values())})
            for body in (f'PROJECT SAVE {PROJECT}', f'NET LOAD DB {PROJECT}', f'NET OPEN {NET}'):
                result['setup'].append({'command': body, 'lines': sanitize(admin.run(body), passwords.values())})
            deadline = time.monotonic() + 45
            state = []
            while time.monotonic() < deadline:
                state = admin.run(f'GET {NET} state')
                if any('state=ok' in line for line in state):
                    break
                time.sleep(.2)
            result['network_state'] = state
            # Lighting group objects are created on first reference by a
            # control command; the database row alone leaves them absent.
            for body in (f'GET {NET}/56 Groups', f'OFF {NET}/56/1', f'GET {NET}/56 Groups'):
                result['setup'].append({'command': body, 'lines': sanitize(admin.run(body), passwords.values())})
            sessions = {}
            for level in passwords:
                session = Session(oracle.port)
                session.run(f'LOGIN obj-{level.lower()} {passwords[level]}')
                sessions[level] = (session, session.run('LOGIN'))
            for object_class, kind, body, levels in MATRIX:
                row = {'object': object_class, 'kind': kind, 'command': body, 'responses': {}}
                for level in levels:
                    session, query = sessions[level]
                    row['responses'][level] = {'session': query,
                                               'lines': sanitize(session.run(body), passwords.values())}
                result['matrix'].append(row)
            for session, _ in sessions.values():
                session.close()
            for body in (f'NET CLOSE {NET}', f'PROJECT CLOSE {PROJECT}', f'PROJECT DELETE {PROJECT}'):
                result['cleanup'].append({'command': body, 'lines': sanitize(admin.run(body), passwords.values())})
            admin.close()
        finally:
            local = oracle.close()
    result['native'] = {'cgate_jar_sha256': local['vendor_jar_sha256'], 'java_version': local['java_version'],
                        'cleanup_complete': local['cleanup_complete']}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', default=None)
    parser.add_argument('--java', default=None)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import os
    vendor = args.vendor or os.environ['CBUS_LOCAL_CGATE_VENDOR']
    java = args.java or os.environ['CBUS_CGATE_JAVA']
    result = capture(vendor, java)
    result.update({
        'schema': 'cbus-native-object-authorization-probe-v1',
        'captured_at': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'scope': 'Owned native C-Gate + synthetic PCI on loopback; no physical C-Bus endpoint',
        'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'fixture_sha256': hashlib.sha256(
            (REPOSITORY / 'toolkit-cli/research/unit_diagnostics_fixture.py').read_bytes()).hexdigest(),
    })
    args.output.write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    print(json.dumps({row['command']: {lvl: r['lines'][-1:] for lvl, r in row['responses'].items()}
                      for row in result['matrix']}, indent=1))


if __name__ == '__main__':
    main()
