"""Offline SESU 3.0.7 metadata-signature chain and revocation policy.

This evaluates a caller-supplied signing chain, signed ``rv1`` revocation
lists and revocation-signer certificates under an explicit anchor profile and
UTC instant. The ordered checks follow the original MultiPlatformUpdate
revocation traversal (RVA 0x39FC) and final metadata validator (RVA 0x37E0);
the chain-policy stage emulates its ``X509Chain.Build`` call
(``RevocationMode.NoCheck`` with ``AllowUnknownCertificateAuthority``).

Nothing is fetched, no certificate store or registry is read and no platform
clock is consulted. A pass means "trusted under the supplied anchor profile
and supplied lists at the supplied instant"; it is not a current publisher
trust decision and it does not reproduce Windows CryptoAPI.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import re

from .toolkit_update_metadata import (CLOCK_SKEW_SECONDS, MAX_CERTIFICATE_BYTES, MAX_NODE_BYTES, MAX_TICKS,
    MAX_TOKEN_CHARACTERS, TICKS_PER_SECOND, _Domain, _bytes, _encode, _epoch, _error, _json, _token,
    _verify_signature, validate_context)
from .toolkit_update_revocation import ORIGINAL_ASSEMBLY_SHA256, _canonical as _revocation_canonical

PROFILE = 'toolkit-1.18-sesu-3.0.7-metadata-trust'
ANCHORS_FORMAT = 'cbus-toolkit-update-trust-anchors-v1'
EMBEDDED_PROFILE = 'sesu-3.0.7-embedded-whitelistcert'
STAGES = ('anchor_profile', 'certificate_inputs', 'original_traversal', 'node_signature_revocation', 'chain_policy')
MAX_TRAVERSAL = 10  # WhiteListCert maximum-depth field set by the initializer at RVA 0x5ED0.
MAX_CERTIFICATES = 16
MAX_ANCHORS = 16
_THUMBPRINT = re.compile(r'[0-9A-F]{40}\Z', re.ASCII)
_SHA256 = re.compile(r'[0-9a-f]{64}\Z', re.ASCII)

# SHA-256 of each pinned GetPublicKeyString byte value from the unchanged
# WhiteListCert initializer. Full values are in the revocation vector fixture.
_EMBEDDED = {
    'roots': (('1F8B978A8B484BFA0FC53F62E63C6BF5640A1A93', 'b73539b60339815c160b974b7b2e94c7cc3b3a1e9d040c0e9a5406c717c221ce'),
              ('7D1B149F71DA7A77DFCBC1D99AD6E11F970527C6', '7cfa0382bb3a60be4d17a20266562c53611a882bbd1cbc476ff47515297fde67')),
    'revocation_signers': (('85CAABAC10E725ED52593159E9B3E6AB5FFD70E2', 'df2b12359af4f60e7f302ae3973b887227c46a4c9fb04d6ca4c903edcdd79e12'),
                           ('B60A284CC105A1D5D2EC839C0E03B39D8E4AF0C8', 'bc53669fc3556d28c65cdcbd79fe0aed9222fb9efd5d547c9b7cbdeb8f4f6b89')),
}


class TrustInputError(ValueError):
    """Malformed, ambiguous or unbound trust input."""


def _der_items(data, offset, end):
    """Yield (tag, start, content_start, content_end) for DER items in a range."""
    while offset < end:
        tag = data[offset]
        length = data[offset + 1]
        header = 2
        if length & 0x80:
            count = length & 0x7F
            if not 1 <= count <= 4:
                raise TrustInputError('Unsupported DER length')
            length = int.from_bytes(data[offset + 2:offset + 2 + count], 'big')
            header += count
        start = offset + header
        if start + length > end:
            raise TrustInputError('Truncated DER')
        yield tag, offset, start, start + length
        offset = start + length


def _raw_names(tbs):
    """Raw issuer and subject Name DER from TBSCertificate bytes.

    The original compares X500DistinguishedName.Name display strings. Raw DER
    equality is used here so that no name is rendered or normalized.
    """
    (_tag, _start, content, end), = list(_der_items(tbs, 0, len(tbs)))
    items = list(_der_items(tbs, content, end))
    if items and items[0][0] == 0xA0:
        items = items[1:]
    if len(items) < 5:
        raise TrustInputError('Unsupported TBSCertificate shape')
    issuer, subject = items[2], items[4]
    return bytes(tbs[issuer[1]:issuer[3]]), bytes(tbs[subject[1]:subject[3]])


class _Certificate:
    def __init__(self, der, role):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        _bytes(der, role, MAX_CERTIFICATE_BYTES)
        self.der = der
        self.role = role
        self.thumbprint = hashlib.sha1(der).hexdigest().upper()
        self.sha256 = hashlib.sha256(der).hexdigest()
        try:
            self.certificate = x509.load_der_x509_certificate(der)
            self.issuer, self.subject = _raw_names(self.certificate.tbs_certificate_bytes)
            self.key = self.certificate.public_key()
        except (ValueError, TypeError, IndexError) as error:
            raise TrustInputError(role + ' is not a readable DER certificate') from error
        except Exception as error:  # cryptography UnsupportedAlgorithm
            raise TrustInputError(role + ' uses an unsupported public-key algorithm') from error
        self.rsa = isinstance(self.key, rsa.RSAPublicKey)
        # GetPublicKeyString for RSA is the PKCS1 RSAPublicKey DER value.
        self.public_key_sha256 = (hashlib.sha256(self.key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.PKCS1)).hexdigest() if self.rsa else None)

    def pin(self):
        return self.thumbprint, self.public_key_sha256

    def summary(self):
        return {'role': self.role, 'thumbprint_sha1': self.thumbprint, 'der_sha256': self.sha256,
                'public_key_sha256': self.public_key_sha256}


def anchor_pins_from_certificates(*, roots=(), revocation_signers=()):
    """Build an anchor-profile document from private DER files supplied at runtime."""
    def pins(values, role):
        return [{'thumbprint_sha1': c.thumbprint, 'public_key_sha256': c.public_key_sha256}
                for c in (_Certificate(value, role) for value in values)]
    return _encode({'format': ANCHORS_FORMAT, 'roots': pins(roots, 'anchor root'),
                    'revocation_signers': pins(revocation_signers, 'anchor revocation signer')}, sorted_keys=True)


def load_anchor_profile(raw=None):
    """Return (profile document, source SHA-256) for the embedded or supplied anchors."""
    if raw is None:
        return ({'id': EMBEDDED_PROFILE, 'source': 'original WhiteListCert initializer RVA 0x5ED0',
                 'original_assembly_sha256': ORIGINAL_ASSEMBLY_SHA256,
                 'roots': [{'thumbprint_sha1': t, 'public_key_sha256': k} for t, k in _EMBEDDED['roots']],
                 'revocation_signers': [{'thumbprint_sha1': t, 'public_key_sha256': k}
                                        for t, k in _EMBEDDED['revocation_signers']]}, None)
    _bytes(raw, 'anchor profile', 64 * 1024)
    value = _json(raw, limit=64 * 1024, depth_limit=4)
    if type(value) is not dict or set(value) != {'format', 'roots', 'revocation_signers'} or value['format'] != ANCHORS_FORMAT:
        raise TrustInputError('Anchor profile must be ' + ANCHORS_FORMAT + ' with roots and revocation_signers only')
    for name in ('roots', 'revocation_signers'):
        rows = value[name]
        if type(rows) is not list or not 1 <= len(rows) <= MAX_ANCHORS:
            raise TrustInputError(name + ' must list 1..16 pins')
        for row in rows:
            if (type(row) is not dict or set(row) != {'thumbprint_sha1', 'public_key_sha256'}
                    or type(row['thumbprint_sha1']) is not str or not _THUMBPRINT.fullmatch(row['thumbprint_sha1'])
                    or type(row['public_key_sha256']) is not str or not _SHA256.fullmatch(row['public_key_sha256'])):
                raise TrustInputError('Each pin needs an uppercase SHA-1 thumbprint and lowercase public-key SHA-256')
        if len({row['thumbprint_sha1'] for row in rows}) != len(rows):
            raise TrustInputError(name + ' repeats a thumbprint')
    return ({'id': 'supplied', 'roots': value['roots'], 'revocation_signers': value['revocation_signers']},
            hashlib.sha256(raw).hexdigest())


def _pinned(certificate, rows):
    # Original predicate RVA 0x3CD0: exact thumbprint key and public-key value.
    return any(row['thumbprint_sha1'] == certificate.thumbprint and row['public_key_sha256'] == certificate.public_key_sha256
               for row in rows)


def _revocation_document(raw):
    _bytes(raw, 'revocation list', MAX_NODE_BYTES)
    value = _json(raw)
    if type(value) is dict and set(value) >= {'success', 'statusCode', 'data'}:
        if value['success'] is not True or type(value['statusCode']) is not int or value['statusCode'] != 200 \
                or type(value['data']) is not dict:
            raise TrustInputError('Revocation response must report success and statusCode 200')
        value = value['data']
    if type(value) is not dict or type(value.get('id')) is not str or not _THUMBPRINT.fullmatch(value['id']):
        raise TrustInputError('Each supplied revocation list needs an uppercase 40-digit id naming its certificate')
    return value


def _lifetime_failure(payload, ticks):
    expires = _epoch(payload['exp']) if 'exp' in payload else None
    begins = _epoch(payload['nbf']) if 'nbf' in payload else None
    if expires is None:
        return 'missing_expiration'
    if begins is not None and begins > expires:
        return 'not_before_after_expiration'
    if begins is not None and begins > min(MAX_TICKS, ticks + CLOCK_SKEW_SECONDS * TICKS_PER_SECOND):
        return 'not_yet_valid'
    if expires < max(0, ticks - CLOCK_SKEW_SECONDS * TICKS_PER_SECOND):
        return 'expired'
    return None


class _Stop(Exception):
    def __init__(self, status, reason, **details):
        super().__init__(reason)
        self.status, self.reason, self.details = status, reason, details


def _check_list(certificate, document, signers, anchors, ticks):
    """Validate one rv1 list in the original JWT-then-pin order."""
    try:
        canonical, claims = _revocation_canonical(document)
    except _Domain as error:
        raise _Stop('unsupported', 'revocation_list_outside_canonical_domain', detail=str(error))
    signatures = document.get('signatures')
    if type(signatures) is not dict or 'rv1' not in signatures:
        raise _Stop('failed', 'revocation_list_missing_rv1',
                    original_message="RevocationList for certificate '<certificate>' is missing signature 'rv1'.")
    try:
        header, payload, signing_input, signature = _token(document, policy='rv1')
    except (_Domain, ValueError) as error:
        raise _Stop('unsupported', 'revocation_token_outside_rs256_profile', detail=str(error))
    signer = signers.get(header['x5t'])
    if signer is None:
        raise _Stop('failed', 'revocation_signer_certificate_not_supplied', x5t=header['x5t'])
    if header['alg'] != 'RS256' or not signer.rsa or not 2048 <= signer.key.key_size <= 8192:
        raise _Stop('unsupported', 'revocation_signature_outside_rs256_profile')
    if not _verify_signature(signer.key, signature, signing_input):
        raise _Stop('failed', 'revocation_signature_invalid')
    lifetime = _lifetime_failure(payload, ticks)
    if lifetime:
        raise _Stop('failed', 'revocation_token_' + lifetime)
    digest = base64.b64encode(hashlib.sha256(canonical).digest()).decode()
    if payload.get('payload_sha256') != digest:
        raise _Stop('failed', 'revocation_payload_digest_mismatch',
                    original_message='Payload hash and signature mismatch.')
    if not _pinned(signer, anchors['revocation_signers']):
        raise _Stop('failed', 'revocation_signer_not_pinned', signer=signer.thumbprint,
                    original_message="RevocationList for certificate '<certificate>' is invalid as the signing "
                                     "certificate '<signer>' is not trusted.")
    for name in ('revokedCertificates', 'revokedSignatures'):
        if claims[name] is None:
            # HashSet.UnionWith(null) throws in the original traversal.
            raise _Stop('failed', 'revocation_list_null_member', member=name)
    return claims, signer, {'thumbprint_sha1': certificate.thumbprint, 'signer_thumbprint_sha1': signer.thumbprint,
                            'id_matches_certificate': document['id'] == certificate.thumbprint,
                            'canonical_sha256': hashlib.sha256(canonical).hexdigest(),
                            'revoked_certificate_entries': len(claims['revokedCertificates']),
                            'revoked_signature_entries': len(claims['revokedSignatures'])}


_SUPPORTED_CRITICAL = {'2.5.29.19'}  # basicConstraints


def _chain_policy(chain, ticks):
    """Emulate X509Chain.Build(NoCheck, AllowUnknownCertificateAuthority) on one path."""
    from datetime import datetime, timezone
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    instant = datetime(1, 1, 1, tzinfo=timezone.utc).timestamp() + ticks / TICKS_PER_SECOND
    elements = []
    unsupported = []
    for index, item in enumerate(chain):
        status = []
        certificate = item.certificate
        if not certificate.not_valid_before_utc.timestamp() <= instant <= certificate.not_valid_after_utc.timestamp():
            status.append('NotTimeValid')
        issuer = chain[index + 1] if index + 1 < len(chain) else item
        algorithm = certificate.signature_hash_algorithm
        if not issuer.rsa or not isinstance(algorithm, (hashes.SHA256, hashes.SHA384, hashes.SHA512)):
            unsupported.append(item.role + ' signature algorithm is outside RSA PKCS1 SHA-2')
        else:
            try:
                issuer.key.verify(certificate.signature, certificate.tbs_certificate_bytes, padding.PKCS1v15(), algorithm)
            except InvalidSignature:
                status.append('NotSignatureValid')
        if item.issuer != issuer.subject:
            status.append('PartialChain')
        try:
            extensions = list(certificate.extensions)
        except ValueError:
            extensions = None
            unsupported.append(item.role + ' has unreadable extensions')
        for extension in extensions or ():
            if extension.critical and extension.oid.dotted_string not in _SUPPORTED_CRITICAL:
                unsupported.append(item.role + ' has an unsupported critical extension')
        if 0 < index < len(chain) - 1:
            try:
                constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
                ca, depth = constraints.ca, constraints.path_length
            except (x509.ExtensionNotFound, ValueError):
                ca, depth = False, None
            if not ca or (depth is not None and depth < index - 1):
                status.append('InvalidBasicConstraints')
        elif index == len(chain) - 1 and index > 0:
            try:
                constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
                if not constraints.ca:
                    unsupported.append('anchor has basicConstraints CA=false')
            except (x509.ExtensionNotFound, ValueError):
                pass
        if index == len(chain) - 1:
            status.append('UntrustedRoot')
        elements.append({'role': item.role, 'thumbprint_sha1': item.thumbprint, 'status': sorted(status)})
    flags = sorted({flag for row in elements for flag in row['status']})
    return elements, flags, unsupported


@dataclass(frozen=True)
class TrustReport:
    _document: str = field(repr=False)

    def as_dict(self):
        return json.loads(self._document)

    @property
    def status(self):
        return self.as_dict()['status']


def evaluate_update_trust(*, leaf_der, issuer_ders=(), revocation_lists=(), revocation_signer_ders=(),
                          at_utc, anchors=None, node_token=None) -> TrustReport:
    """Evaluate one supplied signing chain under an explicit anchor profile and instant."""
    ticks, time_text = validate_context(at_utc)
    profile, profile_sha256 = load_anchor_profile(anchors)
    if len(issuer_ders) + 1 > MAX_CERTIFICATES or len(revocation_signer_ders) > MAX_CERTIFICATES \
            or len(revocation_lists) > MAX_CERTIFICATES:
        raise TrustInputError('At most 16 certificates, revocation signers and revocation lists are admitted')
    if node_token is not None and (type(node_token) is not str or not 0 < len(node_token) <= MAX_TOKEN_CHARACTERS):
        raise TrustInputError('node_token must be a bounded compact JWT string')
    leaf = _Certificate(leaf_der, 'leaf')
    issuers = [_Certificate(value, 'issuer[%d]' % index) for index, value in enumerate(issuer_ders)]
    signers = {}
    for index, value in enumerate(revocation_signer_ders):
        signer = _Certificate(value, 'revocation_signer[%d]' % index)
        if signer.thumbprint in signers:
            raise TrustInputError('A revocation signer certificate is supplied twice')
        signers[signer.thumbprint] = signer
    lists = {}
    list_hashes = {}
    for raw in revocation_lists:
        document = _revocation_document(raw)
        if document['id'] in lists:
            raise TrustInputError('Two supplied revocation lists name the same certificate')
        lists[document['id']] = document
        list_hashes[document['id']] = hashlib.sha256(raw).hexdigest()
    if len({c.thumbprint for c in [leaf, *issuers]}) != len(issuers) + 1:
        raise TrustInputError('A chain certificate is supplied twice')

    document = {
        'format': 'cbus-toolkit-update-trust-v1', 'profile': PROFILE,
        'scope': 'Supplied chain, revocation lists and anchors at an explicit UTC instant; no fetch or store',
        'evaluation_time_utc': time_text, 'evaluation_ticks_100ns': ticks,
        'anchor_profile': {'id': profile['id'], 'source_sha256': profile_sha256,
                           'root_pins': len(profile['roots']), 'revocation_signer_pins': len(profile['revocation_signers'])},
        'certificates': [c.summary() for c in [leaf, *issuers]],
        'revocation_signers': [c.summary() for c in signers.values()],
        'revocation_list_sha256': list_hashes,
        'node_token_sha256': None if node_token is None else hashlib.sha256(node_token.encode()).hexdigest(),
        'stages': [{'stage': name, 'status': 'not_run'} for name in STAGES],
        'status': None, 'trusted_under_supplied_anchor_profile': None,
        'current_publisher_trust_established': False, 'revocation_lists_fetched': False,
        'certificate_store_accessed': False, 'network_accessed': False, 'registry_accessed': False,
        'windows_chain_engine_executed': False,
    }
    rows = {row['stage']: row for row in document['stages']}
    rows['anchor_profile'].update(status='passed', anchor_profile=profile['id'])
    if not leaf.rsa or any(not c.rsa for c in issuers):
        rows['certificate_inputs'].update(status='unsupported', reason='Only RSA chain certificates are supported')
        return _finish(document)
    rows['certificate_inputs'].update(status='passed', chain_certificates=len(issuers) + 1,
                                      revocation_signers=len(signers), revocation_lists=len(lists))

    # Original traversal (RVA 0x39FC) with supplied inputs instead of fetches.
    by_subject = {}
    for issuer in issuers:
        by_subject.setdefault(issuer.subject, []).append(issuer)
    steps, traversed, revoked_certificates, revoked_signatures = [], [], set(), set()
    current, anchor = leaf, None
    try:
        for _ in range(MAX_TRAVERSAL):
            listed = lists.get(current.thumbprint)
            if listed is None:
                raise _Stop('failed', 'revocation_list_not_supplied', certificate=current.role,
                            note='The original would request it from the update server')
            claims, _signer, step = _check_list(current, listed, signers, profile, ticks)
            step['role'] = current.role
            steps.append(step)
            revoked_signatures.update(claims['revokedSignatures'])
            revoked_certificates.update(claims['revokedCertificates'])
            traversed.append(current)
            # Default HashSet<string>: exact ordinal comparison with uppercase GetCertHashString.
            hits = [c.role for c in traversed if c.thumbprint in revoked_certificates]
            if hits:
                raise _Stop('failed', 'certificate_revoked', revoked=hits,
                            original_message="Certificate chain beginning with certificate '<leaf>' contains revoked certificate(s).")
            if _pinned(current, profile['roots']):
                anchor = current
                break
            if current.issuer == current.subject:
                raise _Stop('failed', 'self_signed_certificate_not_pinned', certificate=current.role,
                            original_message="Certificate '<certificate>' is selfsigned without being a CA.")
            candidates = by_subject.get(current.issuer, [])
            if len(candidates) != 1:
                raise _Stop('failed' if not candidates else 'unsupported',
                            'issuer_not_supplied' if not candidates else 'issuer_name_ambiguous', certificate=current.role,
                            note='The original resolves issuers by display name through the update server')
            current = candidates[0]
        else:
            raise _Stop('failed', 'chain_longer_than_maximum', maximum=MAX_TRAVERSAL,
                        original_message="Certificate chain beginning with certificate '<leaf>' is longer than max chain length 10.")
        unused = sorted(set(lists) - {c.thumbprint for c in traversed})
        unused_certificates = [c.role for c in issuers if c not in traversed]
        if unused or unused_certificates:
            raise _Stop('failed', 'unbound_supplied_input', unused_revocation_lists=unused,
                        unused_certificates=unused_certificates)
        rows['original_traversal'].update(status='passed', steps=steps, anchor=anchor.role,
                                          anchor_thumbprint_sha1=anchor.thumbprint,
                                          revocation_list_id_association='document id (CLI admission rule; the original '
                                                                         'associates by request thumbprint only)')
    except _Stop as stop:
        rows['original_traversal'].update(status=stop.status, reason=stop.reason, steps=steps, **stop.details)
        return _finish(document)

    if node_token is None:
        rows['node_signature_revocation'].update(status='not_run', reason='No node token supplied')
    else:
        revoked = node_token in revoked_signatures
        rows['node_signature_revocation'].update(status='failed' if revoked else 'passed', node_token_revoked=revoked,
                                                 comparison='exact ordinal token membership')
        if revoked:
            return _finish(document)

    elements, flags, unsupported = _chain_policy(traversed, ticks)
    if unsupported:
        rows['chain_policy'].update(status='unsupported', reasons=unsupported, elements=elements)
    else:
        allowed = {'UntrustedRoot'}
        rows['chain_policy'].update(status='passed' if set(flags) <= allowed else 'failed', chain_status=flags,
                                    elements=elements, revocation_mode='NoCheck',
                                    verification_flags=['AllowUnknownCertificateAuthority'],
                                    verification_time='explicit evaluation_time_utc; the original uses DateTime.Now')
    return _finish(document)


def _finish(document):
    statuses = {row['stage']: row['status'] for row in document['stages']}
    if 'failed' in statuses.values():
        document['status'] = 'failed'
    elif 'unsupported' in statuses.values() or statuses['chain_policy'] != 'passed':
        document['status'] = 'unsupported'
    else:
        document['status'] = 'passed'
    document['trusted_under_supplied_anchor_profile'] = {'passed': True, 'failed': False}.get(document['status'])
    document['node_signature_revocation_evaluated'] = statuses['node_signature_revocation'] != 'not_run'
    return TrustReport(json.dumps(document, ensure_ascii=True, allow_nan=False))
