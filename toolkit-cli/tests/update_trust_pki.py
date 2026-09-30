"""Synthetic SESU signing PKI for trust and composite tests.

Keys and certificates are generated in-process for each test run and never
written to the repository. Case semantics mirror the plan in
``research/probe_sesu_trust_policy.py`` so that each outcome can be compared
with the retained original Mono observation.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json

from cbus_toolkit.toolkit_update_revocation import _canonical

AT = '2030-01-01T00:00:00Z'
INSTANT = datetime(2030, 1, 1, tzinfo=timezone.utc)
NOW = int(INSTANT.timestamp())
VALID = {'nbf': -3600, 'exp': 86400}
_KEYS = {}


def key(name):
    from cryptography.hazmat.primitives.asymmetric import rsa
    if name not in _KEYS:
        _KEYS[name] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _KEYS[name]


def encode(value):
    return json.dumps(value, separators=(',', ':')).encode()


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=')


def sign_token(signer_key, thumbprint, policy, digest, lifetime=VALID):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    header = {'alg': 'RS256', 'kid': thumbprint, 'typ': 'JWT', 'x5t': thumbprint, 'pol': policy, 'crit': ['pol']}
    payload = {'nbf': NOW + lifetime['nbf'], 'exp': NOW + lifetime['exp'], 'iat': NOW + lifetime['nbf'],
               'payload_sha256': digest}
    signing = b64(encode(header)) + b'.' + b64(encode(payload))
    return (signing + b'.' + b64(signer_key.sign(signing, padding.PKCS1v15(), hashes.SHA256()))).decode()


class Chain:
    def __init__(self, roles):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.x509.oid import NameOID
        self.der = {}
        certificates = {}
        pending = dict(roles)
        while pending:
            for name, spec in list(pending.items()):
                issuer, signer = spec.get('issuer'), spec.get('signer_key')
                if issuer not in (None, *certificates) or signer not in (None, *certificates):
                    continue
                subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic SESU ' + name)])
                window = spec.get('window', (-1, 365))
                builder = (x509.CertificateBuilder().subject_name(subject)
                           .issuer_name(subject if issuer is None else certificates[issuer].subject)
                           .public_key(key(name).public_key()).serial_number(x509.random_serial_number())
                           .not_valid_before(INSTANT + timedelta(days=window[0]))
                           .not_valid_after(INSTANT + timedelta(days=window[1])))
                if spec.get('ca'):
                    builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                signing_key = key(signer or issuer or name)
                certificates[name] = builder.sign(signing_key, hashes.SHA256())
                self.der[name] = certificates[name].public_bytes(serialization.Encoding.DER)
                del pending[name]

    def thumbprint(self, name):
        return hashlib.sha1(self.der[name]).hexdigest().upper()

    def public_key_sha256(self, name):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        public = x509.load_der_x509_certificate(self.der[name]).public_key()
        return hashlib.sha256(public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)).hexdigest()

    def anchors(self, roots=('root',), signers=('signer',)):
        return encode({'format': 'cbus-toolkit-update-trust-anchors-v1',
                       'roots': [{'thumbprint_sha1': self.thumbprint(n), 'public_key_sha256': self.public_key_sha256(n)}
                                 for n in roots] or [{'thumbprint_sha1': '0' * 40, 'public_key_sha256': '0' * 64}],
                       'revocation_signers': [{'thumbprint_sha1': self.thumbprint(n),
                                               'public_key_sha256': self.public_key_sha256(n)}
                                              for n in signers] or [{'thumbprint_sha1': '0' * 40,
                                                                     'public_key_sha256': '0' * 64}]})

    def revocation_list(self, name, *, signer='signer', signed=True, lifetime=VALID, revoked_certificates=(),
                        revoked_signatures=(), id=None, node_token=None):
        entries = []
        for item in revoked_certificates:
            if item == '$LEAF_LOWER':
                entries.append(self.thumbprint('leaf').lower())
            else:
                entries.append(self.thumbprint(item) if item in self.der else item)
        value = {'id': id or self.thumbprint(name), 'signatures': {},
                 'revokedCertificates': entries,
                 'revokedSignatures': [node_token if item == '$NODE_TOKEN' else item for item in revoked_signatures]}
        if signed:
            canonical, _ = _canonical(copy.deepcopy(value))
            digest = base64.b64encode(hashlib.sha256(canonical).digest()).decode()
            value['signatures']['rv1'] = sign_token(key(signer), self.thumbprint(signer), 'rv1', digest, lifetime)
        return encode(value)


def lists(*names, **changes):
    return [dict({'for': name}, **changes.get(name, {})) for name in names]
