"""Run the owned SESU trust-policy and version-comparator probes on Mono.

The runner generates fresh synthetic certificates for every run, executes the
unchanged original assemblies through owned reflection harnesses under a
network-denial sandbox, archives the raw run outside the repository and
writes sanitized committed fixtures. Synthetic keys and certificates are never
committed; only case semantics and original outcomes are retained.

    python research/probe_sesu_trust_policy.py --runtime DIR --out-dir research/fixtures
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

RUNTIME = Path("/Volumes/external/mac-mini-offload/source-cbus/toolkit-cli-research-runtime")
MONO_SUFFIX = "mono-macos-owned/expanded/mono.pkg/Payload/Library/Frameworks/Mono.framework/Versions/6.12.0"
REFERENCES = ("se.dad.core.client", "se.dad.core.common", "se.dad.core.public", "se.dad.services.clientapi.client",
              "se.dad.services.clientapi.api", "se.dad.sesu.common", "newtonsoft.json", "se.dad.signature.api",
              "se.dad.signature.client", "sesubrick.dad", "microsoft.identitymodel.tokens",
              "microsoft.identitymodel.logging", "serilog")
HERE = Path(__file__).resolve().parent


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PKI:
    """Fresh synthetic RSA certificates without extensions, like the product chain."""

    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        self.rsa = rsa
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.keys = {}
        self.certificates = {}

    def key(self, name):
        if name not in self.keys:
            self.keys[name] = self.rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return self.keys[name]

    def issue(self, name, *, issuer=None, signer_key=None, window=(-1, 365), ca=False):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.x509.oid import NameOID
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic SESU " + name)])
        issuer_name = subject if issuer is None else self.certificates[issuer].subject
        key = self.key(name)
        signing = key if issuer is None and signer_key is None else self.key(signer_key or issuer)
        builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(self.now + timedelta(days=window[0]))
                   .not_valid_after(self.now + timedelta(days=window[1])))
        if ca:
            builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        self.certificates[name] = builder.sign(signing, hashes.SHA256())
        return self.certificates[name]

    def der(self, name):
        from cryptography.hazmat.primitives import serialization
        return self.certificates[name].public_bytes(serialization.Encoding.DER)

    def key_xml(self, name):
        numbers = self.key(name).private_numbers()
        size = (self.key(name).key_size + 7) // 8
        half = (size + 1) // 2
        def b64(value, length):
            return base64.b64encode(value.to_bytes(length, "big")).decode()
        public = numbers.public_numbers
        return ("<RSAKeyValue><Modulus>%s</Modulus><Exponent>%s</Exponent><P>%s</P><Q>%s</Q><DP>%s</DP>"
                "<DQ>%s</DQ><InverseQ>%s</InverseQ><D>%s</D></RSAKeyValue>") % (
            b64(public.n, size), b64(public.e, 3), b64(numbers.p, half), b64(numbers.q, half),
            b64(numbers.dmp1, half), b64(numbers.dmq1, half), b64(numbers.iqmp, half), b64(numbers.d, size))


VALID = {"nbf": -3600, "exp": 86400}


def lists(*names, signer="signer", **changes):
    rows = []
    for name in names:
        row = {"for": name, "signer": signer, "signed": True, "lifetime": VALID,
               "revoked_certificates": [], "revoked_signatures": []}
        row.update(changes.get(name, {}))
        rows.append(row)
    return rows


def trust_cases():
    """Case plan; each entry is (label, certificate roles, pins, lists, node lifetime)."""
    windows = {"expired": (-30, -1), "not_yet_valid": (1, 30)}
    cases = []

    def case(label, *, roles=None, pin_roots=("root",), pin_signers=("signer",), revocation=None,
             node_lifetime=VALID, leaf="leaf"):
        roles = roles or {"root": {}, "leaf": {"issuer": "root"}, "signer": {}}
        cases.append({"label": label, "roles": roles, "leaf": leaf, "pin_roots": list(pin_roots),
                      "pin_signers": list(pin_signers),
                      "revocation_lists": revocation if revocation is not None else lists("leaf", "root"),
                      "node_lifetime": node_lifetime})

    case("valid")
    case("leaf-expired", roles={"root": {}, "leaf": {"issuer": "root", "window": windows["expired"]}, "signer": {}})
    case("leaf-not-yet-valid", roles={"root": {}, "leaf": {"issuer": "root", "window": windows["not_yet_valid"]}, "signer": {}})
    case("root-expired", roles={"root": {"window": windows["expired"]}, "leaf": {"issuer": "root"}, "signer": {}})
    case("wrong-anchor-unpinned-root", pin_roots=())
    case("leaf-revoked-in-root-list", revocation=lists("leaf", "root", root={"revoked_certificates": ["leaf"]}))
    case("leaf-revoked-in-own-list", revocation=lists("leaf", "root", leaf={"revoked_certificates": ["leaf"]}))
    case("leaf-revoked-lowercase-entry", revocation=lists("leaf", "root", root={"revoked_certificates": ["$LEAF_LOWER"]}))
    case("root-revoked-in-own-list", revocation=lists("leaf", "root", root={"revoked_certificates": ["root"]}))
    case("node-token-revoked", revocation=lists("leaf", "root", root={"revoked_signatures": ["$NODE_TOKEN"]}))
    case("revocation-signer-unpinned", pin_signers=())
    case("revocation-signer-certificate-expired",
         roles={"root": {}, "leaf": {"issuer": "root"}, "signer": {"window": windows["expired"]}})
    case("revocation-list-token-expired", revocation=lists("leaf", "root", leaf={"lifetime": {"nbf": -7200, "exp": -3600}}))
    case("revocation-list-token-expired-within-skew",
         revocation=lists("leaf", "root", leaf={"lifetime": {"nbf": -7200, "exp": -120}}))
    case("revocation-list-id-mismatch", revocation=lists("leaf", "root", leaf={"id": "0" * 40}))
    case("revocation-list-missing-rv1", revocation=lists("leaf", "root", leaf={"signed": False}))
    case("root-revocation-list-missing-rv1", revocation=lists("leaf", "root", root={"signed": False}))
    case("leaf-signature-by-other-key",
         roles={"root": {}, "other": {}, "leaf": {"issuer": "root", "signer_key": "other"}, "signer": {}})
    case("node-token-expired", node_lifetime={"nbf": -7200, "exp": -3600})
    three = {"root": {}, "inter": {"issuer": "root"}, "leaf": {"issuer": "inter"}, "signer": {}}
    case("intermediate-valid", roles=three, revocation=lists("leaf", "inter", "root"))
    case("intermediate-revoked-in-root-list", roles=three,
         revocation=lists("leaf", "inter", "root", root={"revoked_certificates": ["inter"]}))
    case("intermediate-expired", roles={**three, "inter": {"issuer": "root", "window": windows["expired"]}},
         revocation=lists("leaf", "inter", "root"))
    ca_three = {"root": {}, "inter": {"issuer": "root", "ca": True}, "leaf": {"issuer": "inter"}, "signer": {}}
    case("intermediate-ca-valid", roles=ca_three, revocation=lists("leaf", "inter", "root"))
    case("intermediate-ca-expired", roles={**ca_three, "inter": {"issuer": "root", "ca": True, "window": windows["expired"]}},
         revocation=lists("leaf", "inter", "root"))
    case("root-ca-extension-valid", roles={"root": {"ca": True}, "leaf": {"issuer": "root"}, "signer": {}})
    for length in (10, 11):
        roles = {"root": {}, "signer": {}}
        previous = "root"
        for index in range(1, length - 1):
            roles["c%d" % index] = {"issuer": previous, "ca": True}
            previous = "c%d" % index
        roles["leaf"] = {"issuer": previous}
        names = ["leaf"] + ["c%d" % index for index in range(length - 2, 0, -1)] + ["root"]
        case("chain-length-%d" % length, roles=roles, revocation=lists(*names))
    return cases


def build_plan(cases):
    pki_rows = []
    for item in cases:
        pki = PKI()
        pending = dict(item["roles"])
        while pending:
            for name, spec in list(pending.items()):
                if spec.get("issuer") in (None, *pki.certificates) and spec.get("signer_key") in (None, *pki.certificates):
                    pki.issue(name, issuer=spec.get("issuer"), signer_key=spec.get("signer_key"),
                              window=spec.get("window", (-1, 365)), ca=spec.get("ca", False))
                    del pending[name]
        certificates = {name: {"der": base64.b64encode(pki.der(name)).decode(), "key_xml": pki.key_xml(name)}
                        for name in item["roles"]}
        pki_rows.append({**item, "certificates": certificates})
    return {"cases": pki_rows}


def mono_environment(runtime: Path):
    mono = runtime / MONO_SUFFIX
    source = runtime / "toolkit-update-check/sesu-files"
    alias = runtime / "toolkit-update-validation/assembly-aliases"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MONO_", "DYLD_"))}
    env.update(MONO_CFG_DIR=str(mono / "etc"), MONO_PATH=f"{alias}:{source}:{mono}/lib/mono/4.5",
               DYLD_FALLBACK_LIBRARY_PATH=str(mono / "lib"))
    return mono, source, alias, env


def run_probe(runtime: Path, destination: Path, source_file: Path, main_class: str, arguments, extra_refs=()):
    mono, source, alias, env = mono_environment(runtime)
    exe = destination / (main_class + ".exe")
    compile_command = [str(mono / "bin/mono-sgen64"), str(mono / "lib/mono/4.5/mcs.exe"), "-r:System.Net.Http",
                       "-r:" + str(mono / "lib/mono/4.7.2-api/Facades/netstandard.dll"),
                       "-r:" + str(alias / "System.IdentityModel.Tokens.Jwt.dll"), *extra_refs,
                       *["-r:" + str(source / (name + ".dll")) for name in REFERENCES],
                       "-out:" + str(exe), str(source_file)]
    profile = destination / "network-denied.sb"
    profile.write_text("(version 1)\n(allow default)\n(deny network*)\n")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.1)
    report = {"commands": []}
    stdout = b""
    try:
        for stage, command in (("compile", compile_command),
                               ("run", ["/usr/bin/sandbox-exec", "-f", str(profile), str(mono / "bin/mono-sgen64"),
                                        str(exe), *arguments(listener.getsockname()[1])])):
            process = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
            (destination / (stage + ".stdout")).write_bytes(process.stdout)
            (destination / (stage + ".stderr")).write_bytes(process.stderr)
            report["commands"].append({"stage": stage, "exit_code": process.returncode,
                                       "stdout_sha256": sha(process.stdout), "stderr_sha256": sha(process.stderr)})
            if process.returncode:
                raise SystemExit(stage + " failed: " + process.stderr.decode(errors="replace")[-4000:])
            stdout = process.stdout
        try:
            accepted, _ = listener.accept()
            accepted.close()
            report["unexpected_loopback_connection"] = True
        except socket.timeout:
            report["unexpected_loopback_connection"] = False
    finally:
        listener.close()
    report["executable_sha256"] = sha(exe.read_bytes())
    report["network_sandbox_profile_sha256"] = sha(profile.read_bytes())
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report, [json.loads(line) for line in stdout.decode().splitlines() if line.strip()]


def classify_message(message, thumbprints):
    """Replace ephemeral synthetic thumbprints and tokens with role names."""
    if message is None:
        return None
    for role, value in sorted(thumbprints.items(), key=lambda item: -len(item[1])):
        message = message.replace(value, "<" + role + ">").replace(value.lower(), "<" + role + "-lower>")
    message = re.sub(r"eyJ[A-Za-z0-9_.-]{20,}", "<token>", message)
    return re.sub(r"'[0-9]{1,2}/[0-9]{1,2}/[0-9]{4} [^']*'", "'<time>'", message)


def sanitize_trust(lines, plan):
    sanitized = []
    by_label = {item["label"]: item for item in plan["cases"]}
    for line in lines:
        if line.get("stage") != "original-trust-case":
            if line.get("stage") in ("original-policy-constants", "complete", "network-sandbox-witness"):
                sanitized.append(line)
            continue
        roles = line["thumbprints"]
        role_of = {value: role for role, value in roles.items()}
        traversal = dict(line["original_traversal"])
        if "certificates" in traversal:
            traversal["certificates"] = sorted(role_of[value] for value in traversal["certificates"])
        if "message" in traversal:
            traversal["message"] = classify_message(traversal["message"], roles)
        chain = dict(line["x509_chain_with_original_policy"])
        chain["elements"] = [{"role": role_of.get(e["thumbprint"], "unknown"), "status": e["status"]}
                             for e in chain["elements"]]
        item = by_label[line["label"]]
        sanitized.append({
            "stage": "original-trust-case", "label": line["label"],
            "case": {key: value for key, value in item.items() if key not in ("certificates",)},
            "original_traversal": traversal,
            "x509_chain_with_original_policy": chain,
            "original_is_metadata_validated": line["original_is_metadata_validated"],
            "original_log": [{**event, "message": classify_message(event["message"], roles),
                              "detail": classify_message(event["detail"], roles)} for event in line["original_log"]],
        })
    return sanitized


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=RUNTIME)
    parser.add_argument("--out-dir", type=Path, default=HERE / "fixtures")
    parser.add_argument("--skip-version", action="store_true")
    parser.add_argument("--skip-trust", action="store_true")
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = args.runtime / "toolkit-update-trust" / stamp
    root.mkdir(parents=True, exist_ok=False)
    catalogue = args.runtime / "toolkit-update-check/live-catalog-response.body"
    _, source, _, _ = mono_environment(args.runtime)
    assembly_hashes = {name: sha((source / (name + ".dll")).read_bytes()) for name in ("sesubrick.dad", "se.dad.sesu.common",
                       "se.dad.signature.api", "se.dad.signature.client", "microsoft.identitymodel.tokens")}
    if not args.skip_trust:
        destination = root / "trust"
        destination.mkdir()
        plan = build_plan(trust_cases())
        plan_path = destination / "plan.json"
        plan_path.write_text(json.dumps(plan))
        probe = HERE / "NativeSesuTrustPolicyProbe.cs"
        report, lines = run_probe(args.runtime, destination, probe, "NativeSesuTrustPolicyProbe",
                                  lambda port: [str(plan_path), str(catalogue), str(port)])
        fixture = {
            "format": "cbus-toolkit-update-trust-original-v1",
            "scope": ("Unchanged SESU 3.0.7 MultiPlatformUpdate revocation traversal (RVA 0x39FC), final metadata "
                      "validator (RVA 0x37E0) and X509Chain policy on owned Mono 6.12 over fresh synthetic certificates. "
                      "Synthetic anchors were added only to in-memory WhiteListCert maps; Windows CryptoAPI was not run."),
            "static_policy": json.loads((HERE / "fixtures/toolkit-update-trust-original.json").read_text())["static_policy"],
            "original_assembly_sha256": assembly_hashes,
            "probe_source_sha256": sha(probe.read_bytes()),
            "runner_source_sha256": sha(Path(__file__).read_bytes()),
            "run_report": report,
            "private_run_directory": str(destination.relative_to(args.runtime)),
            "synthetic_material_committed": False,
            "cases": sanitize_trust(lines, plan),
        }
        (args.out_dir / "toolkit-update-trust-original.json").write_text(json.dumps(fixture, indent=1) + "\n")
    if not args.skip_version:
        from probe_sesu_version import run as run_version
        run_version(args, root / "version", assembly_hashes, run_probe)
    print(root)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
