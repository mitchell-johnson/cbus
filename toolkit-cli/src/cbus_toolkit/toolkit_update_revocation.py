"""Independent offline rv1 stages against historical embedded signer identities.

This does not build a chain or establish current publisher trust, complete
revocation status, machine applicability or update availability.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import re

from .toolkit_update_metadata import (MAX_NODE_BYTES, MAX_CERTIFICATE_BYTES,
    MAX_TOKEN_CHARACTERS, CLOCK_SKEW_SECONDS, TICKS_PER_SECOND, MAX_TICKS,
    _Domain, _UnsupportedKey, _bytes, _json, _encode, _token, _load_certificate,
    _verify_signature, _epoch, _error, validate_context)

PROFILE = 'toolkit-1.18-sesu-3.0.7-revocation-rv1'
STAGES = ('canonicalization', 'jwt_parsing', 'certificate_identity',
          'original_revocation_signer_identity', 'jwt_cryptographic_signature',
          'jwt_lifetime', 'payload_digest_claim')
MAX_LIST_ENTRIES = 1024
_IDENTIFIER = re.compile(r'[0-9A-Fa-f]{40}\Z', re.ASCII)
_COMPACT = re.compile(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z', re.ASCII)

# Exact WhiteListCert initializer (RVA0x5ED0), not caller-configurable anchors.
ORIGINAL_ASSEMBLY_SHA256 = '21a6b2fb74d9b308d22c740ca0a1d887d80a067cccc03f59e4dd1bbb6c9c4b0c'
_SIGNER_PINS = (
    ('85CAABAC10E725ED52593159E9B3E6AB5FFD70E2', '3082020A0282020100B1D8652A6E782FF21EB761CD334DC2853E5BE32584F0FF3AD3678F61DCF9083FF9AE82041515A4C7740794B1187603C97E43CC0E56356DD6289ADFEEA87510CB35A228CE85D130ECF370AE5B2367ECBF7003C324F2A46D1ECEF65833BD5781C21B2ACF8EE9D42508A779A591AAEF1944093603F7859ACD80458B7EBC108DBDB3A203BA9E01446B26E42E2D3435A894BFA0A0EEC1866D6F284C610CF9E16247B42A1751873473A3D0FEEFC146C8B2C5E38D17E88A82CC57ABB7769FDD04C3566E4CF19EDD388CF6E3CEAE2DC85EC1F242BED937F0F8CBB9B8559072C9095109142538DC762F4F629A6BD7B1F350364311B5ED192A8EB898976ABDD084FE3334CAE0691F3CF06A6E7D4E5B65F62F250DA600F289FC55F102B4AB3DC62890C84187C1BEBB3D3D96F2193ED7FA9DC0CAE2D6B62FF142AEDF8DED8C21F459D21608B5F89329E8878E5F99DF4167D52972A1BDABEA4B6DB39B18DA652FABACEE929F1933813BA405375B55AE7DB79201610EAE6311AC82C851EAD7C8382B025699C163AC501B30639BE81CDCC7048C6740A0BAC37782B05DF961AE1301C5725C52908C9918D3F5049C66D4E82B1E143293D4963A2FD81A241279C582172FEE047D8DB64AF004A486778E2BEA3F00B5FF6E378AF1C8D9590F920526583F4DD4F1AAE8ECDEA5F569D2E578122B2661968801F573CA5502539FFFBB6CE97FD2834D89DC710203010001'),
    ('B60A284CC105A1D5D2EC839C0E03B39D8E4AF0C8', '3082020A0282020100C83E40080FA57FCA8D05867264809764E898CC91A68605D401F2FABB6B0E7ED0A3BE7AA0763B6361A6A1CDD86A0453F1081E98ADAE87FE3A1E22740D370F0DDF5149C2A7A0BB6543DB8C1BF254530DBDAE240292FEE56682D4740E9C7E6E205674D2F8CDA299785C8BE9B8C0DB208CE19BF74F20DA4E9DA668C33CBD7F34833DE197AEAD5519A38DF8DFC37697D354F45993E7411C870FD67B123AAD77D03D6CDA1F288D9E7F36C912DFBC6340B3CF7E746B8D9E6281E313CC3EB0069E5A6B1444E1EEF6749FD081BDDAA2F4791C950FBC8341DC0978FD2A591259FA4CFB18691FC3CEAEEAAB103AD90B87CF44DB7B8231BC251ADEBC5A3BB19C95FF915E5DC9437059799432736F2665F9614A7400407D22CE3D521EEFD74899021F70080BFA312422EAF69DDA3E747EF98FEAB77CA4BC80158317275E367FE72C6E28384DA8842C67E6218F79E392810CAB23110762F0B0CB68BCFB6F2ECB7E4ADED9FC85A19CD7794A138B24E18C9CE94A20496225807BFBFDC5B35ADAF16E3EE62D288809444EAFD3D974A223EABC89037E1757E96FE47B09463D40CD944D380B78FB5C1C4B227E69F8227F8656B337364FA3BE9A6D321E5A25ABE328919BAB27E2809B8A36F85F36D3004E0F22CAC2A558CF45202698ACE3AB1D50A6F2575ED1374C61D7FFB6991B8327F8550CD42CC7DBCF4CD08BE1EF94EC3869BF632C3AE1587636850203010001'),
)


def select_revocation_data(raw_response: bytes) -> bytes:
    """Select normalized data from a bounded successful captured API response."""
    value = _json(raw_response)
    if (type(value) is not dict or type(value.get('success')) is not bool or value['success'] is not True
            or type(value.get('statusCode')) is not int or value['statusCode'] != 200
            or type(value.get('data')) is not dict):
        raise ValueError('Expected a successful statusCode200 revocation response with an object data field')
    return _encode(value['data'])


def _canonical(value):
    if type(value) is not dict or any(key not in ('id', 'signatures', 'revokedCertificates', 'revokedSignatures') for key in value):
        raise _Domain('Revocation data must contain only the four supported model properties')
    result = {}
    identifier = value.get('id')
    if identifier is not None:
        if type(identifier) is not str or not _IDENTIFIER.fullmatch(identifier):
            raise _Domain('Revocation id must be a40-digit hexadecimal thumbprint, null or omitted')
        result['id'] = identifier
    signatures = value.get('signatures')
    if signatures is not None and (type(signatures) is not dict or len(signatures) > 32 or any(
            type(k) is not str or not 0 < len(k) <= 256 or type(v) is not str or len(v) > MAX_TOKEN_CHARACTERS
            for k, v in signatures.items())):
        raise _Domain('Signatures must be a bounded string map, null or omitted')
    for name in ('revokedCertificates', 'revokedSignatures'):
        entries = value.get(name, [])
        if entries is not None:
            if type(entries) is not list or len(entries) > MAX_LIST_ENTRIES:
                raise _Domain(name + ' must be a bounded list, null or omitted')
            pattern = _IDENTIFIER if name == 'revokedCertificates' else _COMPACT
            bound = 40 if name == 'revokedCertificates' else MAX_TOKEN_CHARACTERS
            if any(type(item) is not str or not 0 < len(item) <= bound or not pattern.fullmatch(item) for item in entries):
                raise _Domain(name + ' contains an entry outside the finite identifier/token domain')
        result[name] = entries
    return _encode(result, sorted_keys=True), result


def _pin_identity(key, thumbprint):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    if not isinstance(key, rsa.RSAPublicKey):
        return False, None
    # GetPublicKeyString is the RSA PKCS1 DER value, not SubjectPublicKeyInfo.
    public_key = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)
    expected = next((value for identity, value in _SIGNER_PINS if identity == thumbprint), None)
    return expected == public_key.hex().upper(), hashlib.sha256(public_key).hexdigest()


@dataclass(frozen=True)
class RevocationStageReport:
    _document: str = field(repr=False)
    cause: BaseException | None = field(default=None, repr=False, compare=False)

    def as_dict(self):
        return json.loads(self._document)

    @property
    def all_supported_stages_passed(self):
        return all(row['status'] == 'passed' for row in self.as_dict()['stages'])


class ToolkitUpdateRevocationStages:
    def __init__(self):
        self.last_report = None

    def evaluate(self, raw_revocation_json: bytes, *, signer_certificate_der: bytes,
                 at_utc, culture='invariant', timezone='UTC') -> RevocationStageReport:
        self.last_report = None
        ticks, time_text = validate_context(at_utc, culture=culture, timezone=timezone)
        _bytes(raw_revocation_json, 'raw_revocation_json', MAX_NODE_BYTES)
        _bytes(signer_certificate_der, 'signer_certificate_der', MAX_CERTIFICATE_BYTES)
        data = _json(raw_revocation_json)
        if type(data) is not dict:
            raise ValueError('Revocation input must be a complete data JSON object')
        document = {'scope': 'Independent offline signed-list stages and historical embedded signer identity',
            'profile': PROFILE, 'original_assembly_sha256': ORIGINAL_ASSEMBLY_SHA256,
            'input_revocation_sha256': hashlib.sha256(raw_revocation_json).hexdigest(),
            'signer_certificate_der_sha256': hashlib.sha256(signer_certificate_der).hexdigest(),
            'signer_certificate_thumbprint_sha1': hashlib.sha1(signer_certificate_der).hexdigest().upper(),
            'evaluation_time_utc': time_text, 'evaluation_ticks_100ns': ticks,
            'clock_skew_seconds': CLOCK_SKEW_SECONDS, 'culture': culture, 'timezone': timezone,
            'publisher_trust': {'status': 'not_evaluated', 'reason': 'Historical embedded identity is not current publisher trust'},
            'certificate_chain': {'status': 'not_evaluated'},
            'complete_revocation_status': {'status': 'not_evaluated', 'reason': 'No chain traversal or complete list set was evaluated'},
            'applicability': {'status': 'not_evaluated'},
            'network_accessed': False, 'registry_accessed': False, 'certificate_store_accessed': False,
            'stages': [{'stage': name, 'status': 'not_run'} for name in STAGES]}
        rows = {row['stage']: row for row in document['stages']}
        current = STAGES[0]
        def record(name, status, **details):
            rows[name].update(status=status, **details)
        def finish(cause=None):
            self.last_report = RevocationStageReport(json.dumps(document, ensure_ascii=True, allow_nan=False), cause)
            return self.last_report
        try:
            canonical = token = key = None
            try:
                canonical, claims = _canonical(data)
                digest = base64.b64encode(hashlib.sha256(canonical).digest()).decode()
                record(current, 'passed', canonical_utf8=canonical.decode(), sha256_base64=digest,
                       sha256_hex=hashlib.sha256(canonical).hexdigest())
                document['claimed_lists'] = {'id': claims.get('id'),
                    'revoked_certificates': claims['revokedCertificates'], 'revoked_signatures': claims['revokedSignatures'],
                    'interpretation': 'Input claims only; no complete-chain membership conclusion',
                    'request_subject_association_verified': False}
            except _Domain as error:
                record(current, 'unsupported', reason=str(error), policy='Explicit finite typed rv1 canonical domain')
            current = 'jwt_parsing'
            try:
                token = _token(data, policy='rv1')
                header, payload, signing_input, signature = token
                record(current, 'passed', algorithm=header['alg'], policy=header['pol'], x5t=header['x5t'],
                       kid_used_as_resolver=False, issuer_validated=False, audience_validated=False)
            except ValueError as error:
                record(current, 'unsupported', reason=str(error), policy='Strict bounded rv1 JWT domain')
            current = 'certificate_identity'
            try:
                key, is_rsa = _load_certificate(signer_certificate_der)
                if token is None:
                    record(current, 'not_run', reason='No supported JWT thumbprint to compare')
                else:
                    matches = header['x5t'] == document['signer_certificate_thumbprint_sha1']
                    record(current, 'passed' if matches else 'failed', thumbprint_matches=matches,
                           rsa_public_key=is_rsa, publisher_trust_evaluated=False)
            except ImportError:
                record(current, 'unsupported', reason='Install the existing research extra to provide cryptography')
            except _UnsupportedKey as error:
                record(current, 'unsupported', reason=str(error), error=_error(error.__cause__ or error))
            except (ValueError, TypeError) as error:
                record(current, 'failed', reason='Supplied DER could not be read', error=_error(error))
            current = 'original_revocation_signer_identity'
            if key is None:
                record(current, 'not_run', reason='Readable supplied key required')
            else:
                matched, public_key_sha256 = _pin_identity(key, document['signer_certificate_thumbprint_sha1'])
                record(current, 'passed' if matched else 'failed', historical_embedded_identity_matches=matched,
                       matched_pin=document['signer_certificate_thumbprint_sha1'] if matched else None,
                       raw_public_key_sha256=public_key_sha256, original_predicate_rva='0x3CD0',
                       original_initializer_rva='0x5ED0', publisher_trust_evaluated=False,
                       certificate_dates_checked=False, certificate_chain_checked=False)
            current = 'jwt_cryptographic_signature'
            signature_valid = None
            if token is None or key is None:
                record(current, 'not_run', reason='Supported JWT and readable supplied key required')
            elif header['alg'] != 'RS256' or not is_rsa or not 2048 <= key.key_size <= 8192:
                record(current, 'unsupported', reason='Only RS256 with a supplied RSA key of2048..8192bits is supported')
            else:
                signature_valid = _verify_signature(key, signature, signing_input)
                record(current, 'passed' if signature_valid else 'failed', signature_valid_for_supplied_key=signature_valid,
                       publisher_trust_evaluated=False, certificate_chain_checked=False)
            current = 'jwt_lifetime'
            qualifiers = {'claims_signature_valid_for_supplied_key': signature_valid, 'publisher_trust_evaluated': False}
            if token is None:
                record(current, 'not_run', reason='JWT claim domain is unsupported', **qualifiers)
            else:
                expires = _epoch(payload['exp']) if 'exp' in payload else None
                begins = _epoch(payload['nbf']) if 'nbf' in payload else None
                failure = ('missing_expiration' if expires is None else
                    'not_before_after_expiration' if begins is not None and begins > expires else
                    'not_yet_valid' if begins is not None and begins > min(MAX_TICKS, ticks + CLOCK_SKEW_SECONDS * TICKS_PER_SECOND) else
                    'expired' if expires < max(0, ticks - CLOCK_SKEW_SECONDS * TICKS_PER_SECOND) else None)
                record(current, 'failed' if failure else 'passed', reason=failure,
                       not_before_ticks_100ns=begins, expiration_ticks_100ns=expires, issued_at_is_lifetime_gate=False, **qualifiers)
            current = 'payload_digest_claim'
            if token is None or canonical is None:
                record(current, 'not_run', reason='Supported JWT and canonical payload required', **qualifiers)
            else:
                matches = payload.get('payload_sha256') == digest
                record(current, 'passed' if matches else 'failed', digest_claim_matches=matches,
                       reason=None if matches else 'Missing or different payload_sha256 claim', **qualifiers)
            return finish()
        except BaseException as error:
            try:
                record(current, 'not_run', reason='Stage interrupted or raised an operational exception', error=_error(error))
                document['interrupted'] = isinstance(error, (KeyboardInterrupt, SystemExit))
                report = finish(error)
            except BaseException:
                emergency = ('{"scope":"Partial offline revocation-stage evidence",'
                    '"evidence_serialization_failed":true,"original_error_retained":true,'
                    '"publisher_trust_evaluated":false,"stages":[{"stage":"' + current + '","status":"not_run"}],'
                    '"input_revocation_sha256":"' + document['input_revocation_sha256'] + '",'
                    '"signer_certificate_der_sha256":"' + document['signer_certificate_der_sha256'] + '"}')
                report = self.last_report = RevocationStageReport(emergency, error)
            try:
                error.toolkit_update_revocation_evidence = report.as_dict()
            except BaseException:
                pass
            raise
