#!/usr/bin/env python3
"""Verify unmodified native C-Gate TLS using an isolated generated PKI.

Requires extracted vendor C-Gate and the research cryptography extra. Docker
remains the default; explicit local mode uses a fresh owned Java11 process
with verified loopback-only listeners. Generated keys are removed at the end.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.local_cgate import LocalCGate, service_backend

IMAGE = "eclipse-temurin:11-jre@sha256:36d9ed86b75e03d756fd4f3b9fdcf952451ddce4a4c451d23cf457ef2d591920"
# Ba.java fixes the keystore path/password; this is a vendor format constant,
# not a user's credential. It protects only generated disposable test keys.
STORE_PASSWORD = "amazing"
EXPECTED_GREETING = "v3.4.0 (build 2001)"


def run(*arguments, cwd=None, timeout=30):
    result = subprocess.run(arguments, cwd=cwd, timeout=timeout, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{arguments[0]} failed: {result.stderr.strip()[:1500]}")
    return result.stdout.strip()


def generate_pki(path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.now(timezone.utc)
    def issuer(name):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
        return key, certificate

    ca_key, ca = issuer("C-Bus disposable TLS test CA")
    rogue_key, rogue = issuer("C-Bus unrelated TLS test CA")
    for name, certificate in (("ca", ca), ("untrusted-ca", rogue)):
        (path / (name + ".pem")).write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    def leaf(name, key, authority, *, server=False, expired=False):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        certificate = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost" if server else name)]))
            .issuer_name(authority.subject).public_key(private.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=2) if expired else now - timedelta(minutes=5))
            .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False))
        if server:
            # DNS-only SAN makes the CLI's127.0.0.1 failure a real hostname test.
            certificate = certificate.add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        certificate = certificate.sign(key, hashes.SHA256())
        (path / (name + ".key")).write_bytes(private.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        os.chmod(path / (name + ".key"), 0o600)
        (path / (name + ".pem")).write_bytes(certificate.public_bytes(serialization.Encoding.PEM)
                                             + authority.public_bytes(serialization.Encoding.PEM))
        return private, certificate

    server_key, server = leaf("server", ca_key, ca, server=True)
    leaf("client", ca_key, ca)
    leaf("expired-client", ca_key, ca, expired=True)
    leaf("untrusted-client", rogue_key, rogue)
    (path / "server.p12").write_bytes(pkcs12.serialize_key_and_certificates(
        b"server", server_key, server, [ca], serialization.BestAvailableEncryption(STORE_PASSWORD.encode())))
    os.chmod(path / "server.p12", 0o600)
    return {"algorithm": "RSA-2048/SHA-256", "server_dns_names": ["localhost"],
            "server_certificate_sha256": server.fingerprint(hashes.SHA256()).hex(),
            "ca_certificate_sha256": ca.fingerprint(hashes.SHA256()).hex()}


def verify(*, vendor_dir=None, output=None, backend=None):
    research = Path(__file__).resolve().parent
    vendor = (Path(vendor_dir) if vendor_dir else research / "vendor/cgate/app").resolve()
    if not (vendor / "cgate.jar").is_file():
        raise RuntimeError("Extract the exact Toolkit vendor installer before this probe")
    backend = service_backend() if backend is None else backend
    if backend not in ("docker", "local"):
        raise ValueError("Native TLS backend must be docker or local")
    name = "cbus-toolkit-tls-" + uuid.uuid4().hex[:10]
    report = {"scope": "Unmodified native C-Gate with generated mutual TLS credentials in an owned disposable loopback service",
              "passed": False, "python": sys.version.split()[0], "openssl": ssl.OPENSSL_VERSION,
              "vendor_jar_sha256": hashlib.sha256((vendor / "cgate.jar").read_bytes()).hexdigest(),
              "backend": backend, "image": IMAGE if backend == "docker" else None, "cases": [], "cleanup_errors": []}
    input_paths = [Path(__file__).resolve(), research / 'local_cgate.py',
                   research.parent / 'src/cbus_toolkit/cgate.py', research.parent / 'src/cbus_toolkit/cli.py',
                   research.parent / 'tests/test_native_tls.py']
    report['source_hashes'] = {str(path.relative_to(research.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in input_paths}
    created = False
    local = LocalCGate(vendor) if backend == "local" else None
    temporary = None if local else tempfile.TemporaryDirectory(prefix="cbus-native-tls-")
    work = local.work if local else Path(temporary.name)
    try:
        for folder in ("config", "tag", "logs", "key", "pki"):
            (work / folder).mkdir(exist_ok=bool(local))
        if not local:
            for folder in ("lib", "unitspec", "help", "transform", "dali_catalogue"):
                (work / folder).symlink_to("/opt/cgate/" + folder, target_is_directory=True)
        else:
            # Remove only the newly copied stock keystore in this owned work
            # directory; TLS acceptance uses solely this run's generated PKI.
            (work / "key/cis.ks").unlink()
        report["generated_pki"] = generate_pki(work / "pki")
        # This builder container runs only keytool; the native server jar
        # is never altered. Its server key and trust anchor share cis.ks.
        base = ([str(local.keytool)] if local else
                ["docker", "run", "--rm", "-v", f"{work}:/work", "-w", "/work", IMAGE, "keytool"])
        run(*base, "-importkeystore", "-noprompt", "-srckeystore", "pki/server.p12", "-srcstoretype", "PKCS12",
            "-srcstorepass", STORE_PASSWORD, "-destkeystore", "key/cis.ks", "-deststoretype", "JKS", "-deststorepass", STORE_PASSWORD,
            cwd=work if local else None)
        run(*base, "-importcert", "-noprompt", "-alias", "test-ca", "-file", "pki/ca.pem",
            "-keystore", "key/cis.ks", "-storepass", STORE_PASSWORD, cwd=work if local else None)
        if local:
            local.start()
            created = True
            port = local.tls_port
        else:
            gateway = json.loads(run("docker", "network", "inspect", "bridge"))[0]["IPAM"]["Config"][0]["Gateway"]
            (work / "config/access.txt").write_text(f"interface 127.0.0.1 Program\nremote {gateway} Program\n")
            (work / "config/C-GateConfig.txt").write_text("secure.bind-address=0.0.0.0\nsecure.port-base=20123\n")
            run("docker", "run", "-d", "--name", name, "--label", "cbus-toolkit.role=disposable-tls-oracle",
                "-p", "127.0.0.1::20123", "-v", f"{vendor}:/opt/cgate:ro", "-v", f"{work}:/work",
                "-w", "/work", IMAGE, "java", "-Xms64M", "-Xmx512M", "-jar", "/opt/cgate/cgate.jar")
            created = True
            ports = json.loads(run("docker", "inspect", name))[0]["NetworkSettings"]["Ports"]
            endpoint = ports["20123/tcp"][0]
            if endpoint["HostIp"] != "127.0.0.1" or set(ports) != {"20123/tcp"}:
                raise RuntimeError("Native TLS fixture must publish only its loopback TLS port")
            port = int(endpoint["HostPort"])
        report["published_tls_port"] = port

        from cbus_toolkit.cgate import CGateClient
        def context(ca="ca", client="client"):
            ctx = ssl.create_default_context(cafile=str(work / "pki" / (ca + ".pem")))
            if client:
                ctx.load_cert_chain(str(work / "pki" / (client + ".pem")), str(work / "pki" / (client + ".key")))
            return ctx
        deadline = time.monotonic() + 30
        while True:
            try:
                with CGateClient("localhost", port, timeout=2, ssl_context=context()) as client:
                    report["greeting"] = client.greeting
                    report["tls_version"] = client._socket.version()
                    report["cipher"] = client._socket.cipher()[0]
                    report["native_noop"] = client.command("NOOP").final
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Verified mutual TLS connection to native C-Gate did not become ready")
                time.sleep(0.1)
        if EXPECTED_GREETING not in report["greeting"]:
            raise RuntimeError("Unexpected native C-Gate version: " + report["greeting"])

        env = os.environ.copy()
        env["PYTHONPATH"] = str(research.parent / "src")
        def cli_case(case, *, hostname="localhost", ca="ca", certificate="client", arguments=None, expected=0):
            command = [sys.executable, "-m", "cbus_toolkit.cli", "cgate", "--host", hostname, "--port", str(port),
                       "--timeout", "5", "--tls", "--ca", str(work / "pki" / (ca + ".pem"))]
            if certificate:
                command.extend(["--cert", str(work / "pki" / (certificate + ".pem")),
                                "--key", str(work / "pki" / (certificate + ".key"))])
            result = subprocess.run(command + (arguments or ["exec", "NOOP"]), env=env, capture_output=True, text=True, timeout=15)
            record = {"case": case, "exit_status": result.returncode, "expected_status": expected,
                      "passed": result.returncode == expected, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
            report["cases"].append(record)
            if not record["passed"]:
                raise RuntimeError("Native TLS case failed: " + case)

        cli_case("verified_mutual_tls_noop")
        project = "TLS" + uuid.uuid4().hex[:5].upper()
        batch = work / "project-commands.txt"
        batch.write_text(f"PROJECT NEW {project}\nPROJECT USE {project}\n"
            f"DBSET //{project}/Project/Description cbus-toolkit-isolated-tls-acceptance-v1\n"
            f"PROJECT SAVE {project}\nPROJECT CLOSE {project}\nPROJECT DELETE {project}\n")
        cli_case("verified_mutual_tls_project_lifecycle", arguments=["run", str(batch)])
        for case, options in (
            ("missing_client_certificate", {"certificate": None}),
            ("untrusted_client_certificate", {"certificate": "untrusted-client"}),
            ("expired_client_certificate", {"certificate": "expired-client"}),
            ("untrusted_server_certificate", {"ca": "untrusted-ca"}),
            ("server_hostname_mismatch", {"hostname": "127.0.0.1"}),
        ):
            cli_case(case, expected=1, **options)
            # Independently retain the TLS-layer failure rather than
            # treating an arbitrary CLI exit1 as proof of authentication.
            negative_context = context(options.get("ca", "ca"), options.get("certificate", "client"))
            try:
                with socket.create_connection(("127.0.0.1", port), 5) as raw:
                    with negative_context.wrap_socket(raw, server_hostname=options.get("hostname", "localhost")) as secured:
                        secured.settimeout(5)
                        secured.recv(4096)  # TLS1.3 client rejection can arrive after handshake.
                raise RuntimeError("Negative TLS case unexpectedly reached the application: " + case)
            except ssl.SSLError as error:
                report["cases"][-1]["tls_failure"] = {"type": type(error).__name__,
                    "reason": error.reason, "verify_code": getattr(error, "verify_code", None)}
        cli_case("verified_connection_after_rejections")
        report["verification_defaults"] = {"check_hostname": context().check_hostname,
                                            "verify_mode": context().verify_mode.name}
        report['source_inputs_changed'] = [str(path.relative_to(research.parent)) for path in input_paths
            if hashlib.sha256(path.read_bytes()).hexdigest() != report['source_hashes'][str(path.relative_to(research.parent))]]
        if report['source_inputs_changed']:
            raise RuntimeError('TLS acceptance source inputs changed during execution')
        report["passed"] = True
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_failure = None
        if created:
            report["server_event_tail"] = [line for path in sorted((work / "logs").glob("event-*.txt"))
                                           for line in path.read_text(errors="replace").splitlines()][-80:]
            if not local:
                try:
                    report["server_log_tail"] = run("docker", "logs", "--tail", "60", name)
                except RuntimeError as error:
                    report["log_error"] = str(error)
                try:
                    run("docker", "rm", "-f", name)
                except RuntimeError as error:
                    report["cleanup_errors"].append(str(error))
                    report["passed"] = False
        if local:
            try:
                local.close()
            except BaseException as error:
                report["cleanup_errors"].append(type(error).__name__ + ": " + str(error))
                report["passed"] = False
                if primary_error is not None:
                    primary_error.tls_harness_cleanup_errors = (*getattr(primary_error, "tls_harness_cleanup_errors", ()), error)
                else:
                    cleanup_failure = error
            finally:
                report["local_service"] = local.report
        elif temporary:
            temporary.cleanup()
        if output:
            target = Path(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2) + "\n")
        if cleanup_failure is not None:
            raise cleanup_failure
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-dir", type=Path)
    parser.add_argument("--backend", choices=("docker", "local"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "runtime/native-tls-acceptance.json")
    args = parser.parse_args()
    report = verify(vendor_dir=args.vendor_dir, output=args.output, backend=args.backend)
    print(json.dumps({key: value for key, value in report.items() if key not in ("server_log_tail", "server_event_tail", "cases")}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
