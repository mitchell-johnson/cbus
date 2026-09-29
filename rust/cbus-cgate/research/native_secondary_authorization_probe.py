#!/usr/bin/env python3
"""Capture native C-Gate 3.4 secondary authorization on owned loopback children.

Two disposable build-2001 children are used. The first changes the live ACCESS
table between event-port connection attempts and records the resulting
admission, 805 refusal event and command-session level. The second records a
LOGIN/LOGOUT transition matrix, live ACCESS edits against existing sessions,
advisory LOCK ownership across LOGIN, EVENT subscription retention and the
per-object read/write/method levels of the root ``cgate`` object.

No C-Bus interface, project, broker or external address is configured. Random
credentials stay in the temporary child; retained replies redact them and the
event rows drop their host-local timestamps and ephemeral ports.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import select
import socket
import time

import native_admin_authorization_probe as base

PORT = re.compile(r'port: \d+')
STAMP = re.compile(r'^\d{8}-\d{6}(?:\.\d{3})?\s+')


def sanitize(line, secrets_seen):
    for value in secrets_seen:
        line = line.replace(value, '<redacted>')
    line = STAMP.sub('', line)
    return PORT.sub('port: <ephemeral>', line)


class Session:
    """One owned command socket with tagged request/response helpers."""

    def __init__(self, oracle, secrets_seen):
        self.sock = socket.create_connection(('127.0.0.1', oracle.port), timeout=5)
        self.sock.settimeout(8)
        self.stream = self.sock.makefile('rwb', buffering=0)
        self.secrets = secrets_seen
        try:
            self.greeting = self.stream.readline().decode(errors='replace').strip()
        except (TimeoutError, socket.timeout):
            self.greeting = '<timeout>'
        except OSError as error:
            self.greeting = f'<{type(error).__name__}>'
        self.count = 0

    def run(self, body):
        self.count += 1
        try:
            lines = base.command(self.stream, f's{self.count}', body)
        except EOFError:
            return ['<eof>']
        except (TimeoutError, socket.timeout):
            return ['<timeout>']
        except OSError as error:
            return [f'<{type(error).__name__}>']
        return [sanitize(line, self.secrets) for line in lines]

    def close(self):
        self.stream.close()
        self.sock.close()


def read_available(peer, seconds):
    """Return (lines, eof) received within ``seconds``."""
    data = b''
    eof = False
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ready, _, _ = select.select([peer], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            break
        try:
            chunk = peer.recv(65536)
        except ConnectionResetError:
            eof = True
            break
        if not chunk:
            eof = True
            break
        data += chunk
    lines = [line.decode(errors='replace').rstrip('\r') for line in data.split(b'\n') if line.strip()]
    return lines, eof


def interface_line(session):
    rows = session.run('ACCESS LIST')
    for row in rows:
        match = re.search(r'line=(\d+) entry=interface ', row)
        if match:
            return match.group(1)
    return None


def event_admission_case(vendor, java):
    secrets_seen = []
    admin_password = secrets.token_hex(24)
    secrets_seen.append(admin_password)
    oracle = base.LocalCGate(vendor, java=java)
    (oracle.work / 'config/access.txt').write_text(
        f'interface 127.0.0.1 Program\nuser sec-admin {admin_password} Clipsal\n')
    result = {'initial_access': ['interface 127.0.0.1 Program', 'user sec-admin <redacted> Clipsal'],
              'steps': []}
    try:
        with oracle:
            watcher = socket.create_connection(('127.0.0.1', oracle.event_port), timeout=5)
            time.sleep(.3)
            admin = Session(oracle, secrets_seen)
            result['admin_greeting'] = admin.greeting
            result['admin_login'] = admin.run(f'LOGIN sec-admin {admin_password}')
            read_available(watcher, .5)
            for label, rule in (('Connect', 'Connect'), ('Monitor', 'Monitor'),
                                ('None-row', 'None'), ('unmatched', None),
                                ('Operate', 'Operate')):
                step = {'case': label}
                line = interface_line(admin)
                if line is not None:
                    step['delete'] = admin.run(f'ACCESS DELETE {line}')
                if rule is not None:
                    step['add'] = admin.run(f'ACCESS ADD interface 127.0.0.1 {rule}')
                step['access_list'] = admin.run('ACCESS LIST')
                probe = socket.create_connection(('127.0.0.1', oracle.event_port), timeout=5)
                probe_lines, probe_eof = read_available(probe, 1.5)
                marker = f'secondary-admission-{label.lower()}'
                step['broadcast'] = admin.run(f'BROADCAST_EVENT SP class {marker}')
                more, more_eof = read_available(probe, 1.5)
                step['new_event_peer'] = {
                    'eof': probe_eof or more_eof,
                    'received_rows': [sanitize(row, secrets_seen) for row in probe_lines + more],
                    'received_marker': any(marker in row for row in probe_lines + more),
                }
                probe.close()
                command_peer = Session(oracle, secrets_seen)
                step['new_command_session'] = {
                    'greeting_prefix': command_peer.greeting[:17] or '<none>',
                    'login_query': command_peer.run('LOGIN'),
                }
                command_peer.close()
                watched, watcher_eof = read_available(watcher, 1.0)
                step['existing_event_peer'] = {
                    'eof': watcher_eof,
                    'rows': [sanitize(row, secrets_seen) for row in watched
                             if re.search(r' 80[3-6] ', row) or marker in row],
                }
                step['admin_level_after'] = admin.run('LOGIN')
                result['steps'].append(step)
            admin.close()
            watcher.close()
        result['cleanup'] = {key: oracle.report[key] for key in (
            'listener_ownership_verified', 'process_exit_confirmed', 'cleanup_complete', 'work_removed')}
        return result
    finally:
        oracle.close()


def login_matrix_case(vendor, java):
    passwords = {level: secrets.token_hex(24) for level in ('None', 'Monitor', 'Program', 'Debug', 'Clipsal', 'Max')}
    secrets_seen = list(passwords.values())
    oracle = base.LocalCGate(vendor, java=java)
    (oracle.work / 'config/access.txt').write_text(
        'interface 127.0.0.1 Operate\n' + ''.join(
            f'user sec-{level.lower()} {password} {level}\n' for level, password in passwords.items()))
    result = {'initial_access': ['interface 127.0.0.1 Operate'] + [
        f'user sec-{level.lower()} <redacted> {level}' for level in passwords]}

    def login(session, level):
        return session.run(f'LOGIN sec-{level.lower()} {passwords[level]}')

    try:
        with oracle:
            s1 = Session(oracle, secrets_seen)
            m = {'greeting_prefix': s1.greeting[:17]}
            m['query_initial'] = s1.run('LOGIN')
            m['wrong_password'] = s1.run(f'LOGIN sec-program {secrets.token_hex(8)}')
            m['query_after_wrong_password'] = s1.run('LOGIN')
            m['unknown_user'] = s1.run(f'LOGIN sec-unknown {passwords["Program"]}')
            m['username_case'] = s1.run(f'LOGIN SEC-PROGRAM {passwords["Program"]}')
            m['missing_password'] = s1.run('LOGIN sec-program')
            m['query_after_failures'] = s1.run('LOGIN')
            m['above_interface'] = login(s1, 'Clipsal')
            m['query_above_interface'] = s1.run('LOGIN')
            m['repeated_downgrade'] = login(s1, 'Monitor')
            m['operate_command_at_monitor'] = s1.run('LOCK cgate')
            m['none_user'] = login(s1, 'None')
            m['query_none_user'] = s1.run('LOGIN')
            m['connect_command_at_none'] = s1.run('NOOP')
            m['login_from_none'] = login(s1, 'Program')
            m['logout'] = s1.run('LOGOUT')
            m['query_after_logout'] = s1.run('LOGIN')
            m['logout_again'] = s1.run('LOGOUT')
            # EVENT subscription and session identity across a LOGIN swap.
            m['event_subscribe'] = s1.run('EVENT e7s0c0')
            m['event_query_before'] = s1.run('EVENT')
            m['login_after_state'] = login(s1, 'Clipsal')
            m['session_id_after_login'] = s1.run('SESSION_ID')
            m['event_query_after_login'] = s1.run('EVENT')
            m['logout_after_state'] = s1.run('LOGOUT')
            m['session_id_after_logout'] = s1.run('SESSION_ID')
            m['event_query_after_logout'] = s1.run('EVENT')
            result['session_matrix'] = m

            # Advisory LOCK ownership across LOGIN/LOGOUT.
            owner = Session(oracle, secrets_seen)
            other = Session(oracle, secrets_seen)
            k = {}
            k['lock'] = owner.run('LOCK cgate')
            k['relock_same_session'] = owner.run('LOCK cgate')
            k['other_session_lock'] = other.run('LOCK cgate')
            k['owner_login'] = login(owner, 'Program')
            k['owner_relock_after_login'] = owner.run('LOCK cgate')
            k['owner_unlock_after_login'] = owner.run('UNLOCK cgate')
            k['other_lock_after_owner_login'] = other.run('LOCK cgate')
            k['other_unlock'] = other.run('UNLOCK cgate')
            k['owner_logout'] = owner.run('LOGOUT')
            k['owner_lock_after_logout'] = owner.run('LOCK cgate')
            owner.close()
            time.sleep(.5)
            k['other_lock_after_owner_close'] = other.run('LOCK cgate')
            k['other_unlock_after_owner_close'] = other.run('UNLOCK cgate')
            other.close()
            result['advisory_lock'] = k

            # Per-object levels on the root cgate object.
            objects = {}
            for level in ('Monitor', 'Operate', 'Program', 'Debug', 'Clipsal', 'Max'):
                session = Session(oracle, secrets_seen)
                if level != 'Operate':
                    login(session, level)
                objects[level] = {
                    'query': session.run('LOGIN'),
                    'get_kcount': session.run('GET cgate KCount'),
                    'get_eventlevel': session.run('GET cgate EventLevel'),
                    'set_eventlevel': session.run('SET cgate EventLevel 5'),
                    'set_state': session.run('SET cgate State new'),
                    'do_gc': session.run('DO cgate gc'),
                }
                session.close()
            result['cgate_object'] = objects

            # Live ACCESS changes against existing sessions and reconnect.
            admin = Session(oracle, secrets_seen)
            existing = Session(oracle, secrets_seen)
            programmed = Session(oracle, secrets_seen)
            a = {'admin_login': login(admin, 'Clipsal'),
                 'existing_query': existing.run('LOGIN'),
                 'programmed_login': login(programmed, 'Program')}
            a['list_at_clipsal'] = admin.run('ACCESS LIST')
            line = interface_line(admin)
            a['delete_interface'] = admin.run(f'ACCESS DELETE {line}')
            a['add_monitor_interface'] = admin.run('ACCESS ADD interface 127.0.0.1 Monitor')
            a['existing_query_after_change'] = existing.run('LOGIN')
            a['existing_operate_command_after_change'] = existing.run('LOCK //MISSING')
            a['existing_logout'] = existing.run('LOGOUT')
            a['existing_operate_command_after_logout'] = existing.run('LOCK //MISSING')
            reconnect = Session(oracle, secrets_seen)
            a['reconnect_query'] = reconnect.run('LOGIN')
            reconnect.close()
            rows = admin.run('ACCESS LIST')
            program_line = next(re.search(r'line=(\d+)', row).group(1) for row in rows
                                if 'entry=user sec-program ' in row)
            a['delete_program_user'] = admin.run(f'ACCESS DELETE {program_line}')
            a['programmed_query_after_delete'] = programmed.run('LOGIN')
            a['programmed_logout'] = programmed.run('LOGOUT')
            a['programmed_relogin_after_delete'] = login(programmed, 'Program')
            a['admin_self_downgrade_list'] = (login(admin, 'Max'), admin.run('ACCESS LIST'))
            existing.close()
            programmed.close()
            admin.close()
            result['live_access'] = a

        result['cleanup'] = {key: oracle.report[key] for key in (
            'listener_ownership_verified', 'process_exit_confirmed', 'cleanup_complete', 'work_removed')}
        return result
    finally:
        oracle.close()


def command_event_case(vendor, java):
    """Which command-trace events a watcher sees for Clipsal-floor families."""
    password = secrets.token_hex(24)
    secrets_seen = [password]
    oracle = base.LocalCGate(vendor, java=java)
    (oracle.work / 'config/access.txt').write_text(
        f'interface 127.0.0.1 Program\nuser sec-clipsal {password} Clipsal\n')
    commands = ['NOOP', 'ACCESS LIST', 'LOG', 'PP LIST_LOCK', 'LOGIN', 'EVENT', 'CONFIG GET cgate-name']
    result = {'commands': commands}
    try:
        with oracle:
            watcher = Session(oracle, secrets_seen)
            result['watcher_mode'] = watcher.run('EVENT e9s0c0')
            actor = Session(oracle, secrets_seen)
            result['actor_login'] = actor.run(f'LOGIN sec-clipsal {password}')
            replies = {}
            for index, body in enumerate(commands):
                replies[body] = actor.run(body)[-1]
            actor.run('NOOP')
            watched, _ = read_available(watcher.sock, 2.0)
            result['replies'] = replies
            result['watcher_rows'] = [sanitize(re.sub(r'^\S+\s+', '', row) if row.startswith('#') else row, secrets_seen)
                                      for row in watched if re.search(r' 76[167] ', row)]
            actor.close()
            watcher.close()
        result['cleanup'] = {key: oracle.report[key] for key in (
            'listener_ownership_verified', 'process_exit_confirmed', 'cleanup_complete', 'work_removed')}
        return result
    finally:
        oracle.close()


def access_control_role_case(vendor, java):
    """Role gradient for the native ACCESSCONTROL root (absent target)."""
    levels = base.LEVELS
    passwords = {level: secrets.token_hex(24) for level in levels}
    secrets_seen = list(passwords.values())
    oracle = base.LocalCGate(vendor, java=java)
    (oracle.work / 'config/access.txt').write_text(
        'interface 127.0.0.1 Clipsal\n' + ''.join(
            f'user sec-{level.lower()} {password} {level}\n' for level, password in passwords.items()))
    commands = ['ACCESSCONTROL', 'ACCESSCONTROL CLOSE //MISSING/254/213 1 1',
                'ACCESSCONTROL LOCK //MISSING/254/213 1 1']
    result = {'commands': commands, 'roles': {}}
    try:
        with oracle:
            for level in levels:
                session = Session(oracle, secrets_seen)
                login = session.run(f'LOGIN sec-{level.lower()} {passwords[level]}')
                result['roles'][level] = {'login': login, 'replies': {
                    body: session.run(body)[-1] for body in commands}}
                session.close()
        result['cleanup'] = {key: oracle.report[key] for key in (
            'listener_ownership_verified', 'process_exit_confirmed', 'cleanup_complete', 'work_removed')}
        return result
    finally:
        oracle.close()


def capture(vendor, java):
    inputs = [Path(__file__), Path(base.__file__), base.REPOSITORY / 'toolkit-cli/research/local_cgate.py']
    hashes = {str(path.relative_to(base.REPOSITORY)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in inputs}
    return {
        'schema': 'native-cgate-secondary-authorization-v1',
        'captured_utc': datetime.now(timezone.utc).isoformat(),
        'scope': ('Owned IPv4 loopback command and event listeners; live ACCESS edits; '
                  'no physical endpoint, site project, IPv6 peer, load-change or config-change port'),
        'oracle': {
            'version': '3.4.0 build 2001',
            'jar_sha256': hashlib.sha256((vendor / 'cgate.jar').read_bytes()).hexdigest(),
            'java_sha256': hashlib.sha256(java.read_bytes()).hexdigest(),
            'source_hashes': hashes,
            'physical_endpoint': False,
        },
        'event_admission': event_admission_case(vendor, java),
        'login_matrix': login_matrix_case(vendor, java),
        'command_events': command_event_case(vendor, java),
        'access_control_roles': access_control_role_case(vendor, java),
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path, required=True)
    parser.add_argument('--java', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = capture(args.vendor.resolve(), args.java.resolve())
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'cleanup': all(report[case]['cleanup']['cleanup_complete']
                                     for case in ('event_admission', 'login_matrix', 'command_events', 'access_control_roles'))}))
