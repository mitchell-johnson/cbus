"""Probe native mutual-TLS admission against ACCESS and LOGIN on loopback.

All PKI and ACCESS credentials are generated in an owned disposable C-Gate
work directory. Only response summaries, public fingerprints and source hashes
are retained. The native process has no project or C-Bus endpoint.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import socket
import ssl
import sys

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / 'toolkit-cli/research'))
from local_cgate import LocalCGate
from verify_tls import STORE_PASSWORD, generate_pki, run


def command(stream, tag, body):
    stream.write(f'[{tag}] {body}\r\n'.encode())
    stream.flush()
    while True:
        raw = stream.readline()
        if not raw:
            raise EOFError((tag, body))
        line = raw.decode(errors='replace').rstrip('\r\n')
        if line.startswith('#'):
            continue
        prefix = f'[{tag}] '
        if not line.startswith(prefix):
            raise ValueError((tag, body, line))
        reply = line[len(prefix):]
        if len(reply) >= 4 and reply[:3].isdigit() and reply[3] == ' ':
            return reply


def capture(vendor, java, output):
    oracle = LocalCGate(vendor, java=java)
    password = secrets.token_hex(24)
    report = {
        'format': 'native-cgate-tls-authorization-probe-v1',
        'captured_at': datetime.now(timezone.utc).isoformat(),
        'oracle': {'version': '3.4.0.2001',
                   'jar_sha256': hashlib.sha256((vendor / 'cgate.jar').read_bytes()).hexdigest(),
                   'java_sha256': hashlib.sha256(java.read_bytes()).hexdigest(),
                   'transport': 'owned Java 11 loopback listener, generated short-lived PKI, empty project set, no C-Bus endpoint'},
        'capture_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'local_cgate_harness_sha256': hashlib.sha256(
            (REPOSITORY / 'toolkit-cli/research/local_cgate.py').read_bytes()
        ).hexdigest(),
        'pki_helper_sha256': hashlib.sha256(
            (REPOSITORY / 'toolkit-cli/research/verify_tls.py').read_bytes()
        ).hexdigest(),
        'method': 'A trusted client certificate with subject CN=client and an ACCESS user named client at Admin was presented. LOGIN was queried before and after username/password login and LOGOUT. No credential or key bytes are retained.',
        'cases': {},
    }
    try:
        (oracle.work / 'pki').mkdir()
        (oracle.work / 'key/cis.ks').unlink()
        report['public_pki'] = generate_pki(oracle.work / 'pki')
        run(str(oracle.keytool), '-importkeystore', '-noprompt',
            '-srckeystore', 'pki/server.p12', '-srcstoretype', 'PKCS12',
            '-srcstorepass', STORE_PASSWORD, '-destkeystore', 'key/cis.ks',
            '-deststoretype', 'JKS', '-deststorepass', STORE_PASSWORD,
            cwd=oracle.work)
        run(str(oracle.keytool), '-importcert', '-noprompt', '-alias', 'test-ca',
            '-file', 'pki/ca.pem', '-keystore', 'key/cis.ks',
            '-storepass', STORE_PASSWORD, cwd=oracle.work)
        (oracle.work / 'config/access.txt').write_text(
            f'interface 127.0.0.1 Clipsal\nuser client {password} Admin\n')
        with oracle:
            def context(with_client):
                ctx = ssl.create_default_context(cafile=str(oracle.work / 'pki/ca.pem'))
                if with_client:
                    ctx.load_cert_chain(str(oracle.work / 'pki/client.pem'),
                                        str(oracle.work / 'pki/client.key'))
                return ctx

            try:
                with socket.create_connection(('127.0.0.1', oracle.tls_port), timeout=5) as raw:
                    with context(False).wrap_socket(raw, server_hostname='localhost') as tls:
                        tls.settimeout(5)
                        tls.recv(4096)
                raise RuntimeError('Client without certificate reached native C-Gate greeting')
            except ssl.SSLError as error:
                report['cases']['missing_client_certificate'] = {
                    'tls_failure_type': type(error).__name__,
                    'tls_failure_reason': error.reason,
                    'greeting_received': False,
                }

            with socket.create_connection(('127.0.0.1', oracle.tls_port), timeout=5) as raw:
                with context(True).wrap_socket(raw, server_hostname='localhost') as tls:
                    tls.settimeout(5)
                    stream = tls.makefile('rwb', buffering=0)
                    greeting = stream.readline().decode().strip()
                    report['cases']['trusted_certificate'] = {
                        'greeting': greeting,
                        'tls_version': tls.version(),
                        'initial_level': command(stream, 'initial', 'LOGIN'),
                        'admin_login': command(stream, 'admin', f'LOGIN client {password}'),
                        'after_login': command(stream, 'elevated', 'LOGIN'),
                        'logout': command(stream, 'logout', 'LOGOUT'),
                        'after_logout': command(stream, 'reset', 'LOGIN'),
                    }
            with socket.create_connection(('127.0.0.1', oracle.tls_port), timeout=5) as raw:
                with context(True).wrap_socket(raw, server_hostname='localhost') as tls:
                    tls.settimeout(5)
                    stream = tls.makefile('rwb', buffering=0)
                    stream.readline()
                    report['cases']['trusted_reconnect'] = {
                        'initial_level': command(stream, 'reconnect', 'LOGIN'),
                    }
    finally:
        report['oracle'].update({key: oracle.report.get(key) for key in (
            'listener_ownership_verified', 'cleanup_complete',
            'process_exit_confirmed', 'work_removed', 'server_log_sha256')})
        output.write_text(json.dumps(report, indent=2) + '\n')
    if not report['oracle']['cleanup_complete']:
        raise RuntimeError('Owned native process cleanup incomplete')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-dir', required=True, type=Path)
    parser.add_argument('--java', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = capture(args.vendor_dir.resolve(), args.java.resolve(), args.output.resolve())
    print(json.dumps({'output': str(args.output), 'cleanup': result['oracle']['cleanup_complete'],
                      'cases': sorted(result['cases'])}))
