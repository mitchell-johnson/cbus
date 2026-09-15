import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit import toolkit_update_metadata as subject

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'research/fixtures/toolkit-update-metadata-vectors.json'
AT = '2030-01-01T00:00:00Z'
NOW = 1893456000


def fixture():
    return json.loads(FIXTURE.read_text())


def captured(index=0):
    return json.loads(fixture()['raw_catalogue_json'])['data'][index]


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def leaf():
    return base64.b64decode(fixture()['leaf_der_base64'])


def owned_der():
    return base64.b64decode(fixture()['owned_test_certificate_der_base64'])


def rows(report):
    return {row['stage']: row for row in report.as_dict()['stages']}


def signed_node(*, claims=None, remove=(), header_changes=None, corrupt=False, raw_payload=None):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    data = fixture()
    node = captured()
    canonical = next(row for row in data['canonical_cases'] if row['id'] == 'canonical-v1/captured-0')
    payload = {'nbf': NOW-3600, 'exp': NOW+3600, 'iat': NOW-3600, 'payload_sha256': canonical['digest_base64']}
    payload.update(claims or {})
    for name in remove:
        payload.pop(name, None)
    thumbprint = hashlib.sha1(owned_der()).hexdigest().upper()
    header = {'alg': 'RS256', 'typ': 'JWT', 'x5t': thumbprint, 'kid': thumbprint, 'pol': 'v1', 'crit': ['pol']}
    header.update(header_changes or {})
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b'=')
    signing_input = b64(encode(header)) + b'.' + b64(encode(payload) if raw_payload is None else raw_payload)
    key = serialization.load_pem_private_key(data['owned_test_key_pem'].encode(), None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    if corrupt:
        signature = bytes((signature[0] ^ 1,)) + signature[1:]
    node['signatures']['v1'] = (signing_input + b'.' + b64(signature)).decode()
    return node


class MetadataTests(unittest.TestCase):
    def evaluate(self, node=None, *, der=None, at=AT, **kwargs):
        return subject.ToolkitUpdateMetadataStages().evaluate(encode(captured() if node is None else node),
            certificate_der=leaf() if der is None else der, at_utc=at, **kwargs)

    def test_seven_actual_signatures_canonical_bytes_and_opaque_der(self):
        original_der = leaf()
        self.assertEqual(hashlib.sha256(original_der).hexdigest(), '5eab9290101efa56854d12421bed8daf8df6f1e4b37c29486da06d2e56f125ab')
        known = {r['id']: r for r in fixture()['canonical_cases']}
        for index in range(7):
            result = self.evaluate(captured(index), at='2026-09-15T02:34:07.1234567Z')
            self.assertTrue(result.all_supported_stages_passed)
            observed = rows(result)
            expected = known['canonical-v1/captured-' + str(index)]
            self.assertEqual(observed['canonicalization']['canonical_utf8'], expected['canonical_json'])
            self.assertEqual(observed['canonicalization']['sha256_base64'], expected['digest_base64'])
            self.assertEqual(observed['jwt_lifetime']['expiration_ticks_100ns'], subject.MAX_TICKS)
            value = result.as_dict()
            self.assertEqual(value['evaluation_time_utc'], '2026-09-15T02:34:07.1234567Z')
            for field in ('publisher_trust', 'revocation', 'applicability'):
                self.assertEqual(value[field]['status'], 'not_evaluated')
            for field in ('metadata_signature_verified', 'updates_available', 'latest_version'):
                self.assertNotIn(field, value)
            self.assertEqual(leaf(), original_der)
            value['stages'][0]['status'] = 'forged'
            self.assertEqual(rows(result)['canonicalization']['status'], 'passed')

    def test_supported_original_canonical_vectors_are_byte_exact(self):
        compared = []; unsupported = []; invalid = []
        editor = subject.ToolkitUpdateMetadataStages()
        for case in fixture()['canonical_cases']:
            raw = case['input_node_json'].encode()
            try:
                result = editor.evaluate(raw, certificate_der=leaf(), at_utc=AT)
            except ValueError:
                invalid.append(case['id'])
                continue
            row = rows(result)['canonicalization']
            if row['status'] == 'passed':
                self.assertTrue(case['completed'], case['id'])
                self.assertEqual(row['canonical_utf8'], case['canonical_json'], case['id'])
                self.assertEqual(row['sha256_base64'], case['digest_base64'], case['id'])
                compared.append(case['id'])
            else:
                self.assertEqual(row['status'], 'unsupported')
                unsupported.append(case['id'])
        self.assertEqual(len(compared), 52)
        self.assertEqual(len(invalid), 1)
        self.assertEqual(len(unsupported), 55)
        self.assertIn('canonical-v1/unicode-values', compared)
        self.assertIn('canonical-v1/minimal-package', compared)
        self.assertIn('canonical-v1/metadata-numeric', invalid)

    def test_excluded_download_urls_do_not_acquire_authentication(self):
        node = captured()
        node['urls'] = {'owned': {'url': 'https://example.invalid/unsigned'}}
        node['files'][0]['url'] = 'file:///not-followed'
        node['header']['versionHistory'] = {'anything': 'ignored by original model'}
        node['header']['revision']['author'] = 'untrusted unsigned text'
        self.assertTrue(self.evaluate(node).all_supported_stages_passed)
        # A signed field still changes the digest while its original signature remains valid.
        node['nodeName'] = 'owned changed name'
        result = rows(self.evaluate(node))
        self.assertEqual(result['jwt_cryptographic_signature']['status'], 'passed')
        self.assertEqual(result['payload_digest_claim']['status'], 'failed')

    def test_signature_failure_does_not_promote_unauthenticated_claims(self):
        result = rows(self.evaluate(signed_node(corrupt=True), der=owned_der()))
        self.assertEqual(result['jwt_cryptographic_signature']['status'], 'failed')
        for name in ('jwt_lifetime', 'payload_digest_claim'):
            self.assertEqual(result[name]['status'], 'passed')
            self.assertIs(result[name]['claims_signature_valid_for_supplied_key'], False)
            self.assertFalse(result[name]['publisher_trust_evaluated'])
        result = rows(self.evaluate(signed_node(claims={'exp': NOW-3600}, corrupt=True), der=owned_der()))
        self.assertEqual(result['jwt_lifetime']['reason'], 'expired')
        self.assertEqual(result['jwt_cryptographic_signature']['status'], 'failed')

    def test_certificate_thumbprint_is_independent_of_signature_for_supplied_key(self):
        result = rows(self.evaluate(signed_node(header_changes={'x5t': '0'*40}), der=owned_der()))
        self.assertEqual(result['certificate_identity']['status'], 'failed')
        self.assertTrue(result['jwt_cryptographic_signature']['signature_valid_for_supplied_key'])
        result = rows(self.evaluate(der=owned_der()))
        self.assertEqual(result['certificate_identity']['status'], 'failed')
        self.assertEqual(result['jwt_cryptographic_signature']['status'], 'failed')
        self.assertEqual(rows(self.evaluate(der=b'not DER'))['certificate_identity']['status'], 'failed')

    def test_unknown_spki_algorithm_is_unsupported_without_aborting_other_stages(self):
        original = leaf()
        rsa_oid = bytes.fromhex('06092a864886f70d010101')
        self.assertEqual(original.count(rsa_oid), 1)
        modified = original.replace(rsa_oid, rsa_oid[:-1] + b'\x63', 1)
        result = rows(self.evaluate(der=modified))
        self.assertEqual(result['certificate_identity']['status'], 'unsupported')
        self.assertEqual(result['certificate_identity']['error']['type'], 'UnsupportedAlgorithm')
        self.assertEqual(result['jwt_cryptographic_signature']['status'], 'not_run')
        self.assertEqual(result['jwt_lifetime']['status'], 'passed')
        self.assertEqual(result['payload_digest_claim']['status'], 'passed')
        self.assertIsNone(result['payload_digest_claim']['claims_signature_valid_for_supplied_key'])
        self.assertEqual(leaf(), original)

    def test_exact_100ns_expiration_and_not_before_skew_boundaries(self):
        expired = signed_node(claims={'exp': NOW-300})
        future = signed_node(claims={'nbf': NOW+300})
        for node, at, expected in ((expired, AT, 'passed'),
            (expired, '2030-01-01T00:00:00.0000001Z', 'failed'),
            (expired, '2029-12-31T23:59:59.9999999Z', 'passed'),
            (future, AT, 'passed'), (future, '2029-12-31T23:59:59.9999999Z', 'failed'),
            (future, '2030-01-01T00:00:00.0000001Z', 'passed')):
            self.assertEqual(rows(self.evaluate(node, der=owned_der(), at=at))['jwt_lifetime']['status'], expected)
        result = self.evaluate(expired, der=owned_der(), at='2030-01-01T00:00:00.0000001Z').as_dict()
        self.assertEqual(result['evaluation_time_utc'], '2030-01-01T00:00:00.0000001Z')
        self.assertEqual(result['evaluation_ticks_100ns'] % 10000000, 1)

    def test_original_epoch_saturation_required_expiration_and_ignored_iat(self):
        for expiration in (253402300800, 9223372036854775807):
            result = rows(self.evaluate(signed_node(claims={'exp': expiration}), der=owned_der()))
            self.assertEqual(result['jwt_lifetime']['status'], 'passed')
            self.assertEqual(result['jwt_lifetime']['expiration_ticks_100ns'], subject.MAX_TICKS)
        for name in ('nbf', 'iat'):
            self.assertEqual(rows(self.evaluate(signed_node(remove=(name,)), der=owned_der()))['jwt_lifetime']['status'], 'passed')
        result = rows(self.evaluate(signed_node(remove=('exp',)), der=owned_der()))
        self.assertEqual(result['jwt_lifetime']['reason'], 'missing_expiration')
        self.assertEqual(rows(self.evaluate(signed_node(claims={'iat': NOW+100000}), der=owned_der()))['jwt_lifetime']['status'], 'passed')
        for exp in (0, -1):
            node = signed_node(claims={'exp': exp}, remove=('nbf',))
            self.assertEqual(rows(self.evaluate(node, der=owned_der(), at='1970-01-01T00:05:00Z'))['jwt_lifetime']['status'], 'passed')
            self.assertEqual(rows(self.evaluate(node, der=owned_der(), at='1970-01-01T00:05:00.0000001Z'))['jwt_lifetime']['reason'], 'expired')

    def test_digest_claim_missing_wrong_or_array_remains_distinct(self):
        for node in (signed_node(remove=('payload_sha256',)), signed_node(claims={'payload_sha256': 'wrong'})):
            result = rows(self.evaluate(node, der=owned_der()))
            self.assertEqual(result['jwt_cryptographic_signature']['status'], 'passed')
            self.assertEqual(result['payload_digest_claim']['status'], 'failed')
        result = rows(self.evaluate(signed_node(claims={'payload_sha256': ['wrong']}), der=owned_der()))
        self.assertEqual(result['jwt_parsing']['status'], 'unsupported')

    def test_narrow_jwt_domain_is_reported_without_disabling_canonical_stage(self):
        for claims in ({'exp': True}, {'exp': str(NOW)}, {'exp': NOW+.5}, {'exp': None}, {'exp': 9223372036854775808}):
            result = rows(self.evaluate(signed_node(claims=claims), der=owned_der()))
            self.assertEqual(result['canonicalization']['status'], 'passed')
            self.assertEqual(result['jwt_parsing']['status'], 'unsupported')
            self.assertEqual(result['jwt_lifetime']['status'], 'not_run')
        node = signed_node(raw_payload=b'{"exp":1893459600,"exp":1893459600}')
        self.assertEqual(rows(self.evaluate(node, der=owned_der()))['jwt_parsing']['status'], 'unsupported')
        for header in ({'pol': 'other'}, {'crit': ['pol', 'other']}, {'typ': 'other'}):
            self.assertEqual(rows(self.evaluate(signed_node(header_changes=header), der=owned_der()))['jwt_parsing']['status'], 'unsupported')
        result = rows(self.evaluate(signed_node(header_changes={'alg': 'RS512'}), der=owned_der()))
        self.assertEqual(result['jwt_cryptographic_signature']['status'], 'unsupported')
        self.assertEqual(result['jwt_lifetime']['status'], 'passed')

    def test_original_lifetime_vectors_agree_where_independent_domains_overlap(self):
        data = fixture(); certs = {item['thumbprint']: base64.b64decode(item['der_base64']) for item in data['lifetime_original_cases']['certificates']}
        originals = {row['id']: row for row in data['lifetime_original_results'] if row['stage'] == 'lifetime-case'}
        checked = []
        for case in data['lifetime_original_cases']['cases']:
            node = captured(); node['signatures']['v1'] = case['token']
            header = json.loads(base64.urlsafe_b64decode(case['token'].split('.')[0]+'=='))
            result = rows(self.evaluate(node, der=certs[header['x5t']], at='2026-09-15T02:34:07.5376940Z'))
            original = originals[case['id']]
            if result['jwt_lifetime']['status'] == 'not_run':
                continue
            error = original.get('error', '')
            if 'ExpiredException' in error or 'NotYetValidException' in error or 'InvalidLifetimeException' in error or 'NoExpirationException' in error:
                self.assertEqual(result['jwt_lifetime']['status'], 'failed', case['id'])
                checked.append(case['id'])
            elif original['accepted']:
                self.assertEqual(result['jwt_lifetime']['status'], 'passed', case['id'])
                checked.append(case['id'])
        self.assertEqual(len(checked), 28)

    def test_json_bounds_and_context_validation_precede_crypto(self):
        invalid = [b'{"x":'+b'9'*100000+b'}', b'{"x":1e999999}', b'{"x":NaN}', b'{"x":Infinity}',
            b'{"x":1,"x":2}', b'{"x":"\\ud800"}', b'{"x":"\\udfff"}', b'{"x":'+b'['*33+b'0'+b']'*33+b'}',
            b'{"x":"\xff"}', b'[]', b'', b' '* (subject.MAX_NODE_BYTES+1)]
        with patch.object(subject, '_load_certificate', side_effect=AssertionError('No crypto before input bounds')):
            for raw in invalid:
                with self.assertRaises(ValueError):
                    subject.ToolkitUpdateMetadataStages().evaluate(raw, certificate_der=b'x', at_utc=AT)
            for at in (None, True, datetime(2030, 1, 1), '2030-01-01', '2030-01-01T00:00:00.12345678Z', '2030-01-01T00:00:00+00:00'):
                with self.assertRaises(ValueError): self.evaluate(at=at)
            for kwargs in ({'culture': 'en-US'}, {'timezone': 'Pacific/Auckland'}, {'culture': True}):
                with self.assertRaises(ValueError): self.evaluate(**kwargs)
        result = self.evaluate(at=datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(result.as_dict()['evaluation_time_utc'], AT)

    def test_date_text_nonfinite_unknown_keys_and_duplicate_assignments_are_not_silently_normalized(self):
        for transform in (
            lambda n:n.update(nodeName='2025-02-17T13:45:00.1234567+13:45'),
            lambda n:n['data']['displayName'].update(fr='unproved locale'),
            lambda n:n['files'][0]['metadata'].update(extra=1.0),
            lambda n:n['assignedTo'].append(copy.deepcopy(n['assignedTo'][0])),
            lambda n:n.update(ownedUnknown=1)):
            node = captured(); transform(node)
            result = rows(self.evaluate(node))
            self.assertEqual(result['canonicalization']['status'], 'unsupported')
            self.assertEqual(result['jwt_cryptographic_signature']['status'], 'passed')
            self.assertEqual(result['payload_digest_claim']['status'], 'not_run')

    def test_no_subject_rendering_or_external_operations_and_missing_optional_dependency(self):
        from cryptography import x509
        actual = x509.load_der_x509_certificate(leaf())
        class Opaque:
            def public_key(self): return actual.public_key()
            @property
            def subject(self): raise AssertionError('Do not render subject')
            @property
            def issuer(self): raise AssertionError('Do not render issuer')
        with patch('cryptography.x509.load_der_x509_certificate', return_value=Opaque()), \
             patch('socket.socket', side_effect=AssertionError('No network')), \
             patch('ssl.create_default_context', side_effect=AssertionError('No TLS/store')):
            self.assertTrue(self.evaluate().all_supported_stages_passed)
        with patch.object(subject, '_load_certificate', side_effect=ImportError('owned absent dependency')):
            result = rows(self.evaluate())
        self.assertEqual(result['canonicalization']['status'], 'passed')
        self.assertEqual(result['certificate_identity']['status'], 'unsupported')
        self.assertEqual(result['jwt_cryptographic_signature']['status'], 'not_run')
        self.assertIsNone(result['jwt_lifetime']['claims_signature_valid_for_supplied_key'])

    def test_interruption_identity_partial_stage_evidence_and_stale_reset(self):
        class Reject(KeyboardInterrupt):
            def __str__(self): raise SystemExit('secondary rendering')
            def __setattr__(self, name, value):
                if name == 'toolkit_update_metadata_evidence': raise SystemExit('secondary attachment')
                super().__setattr__(name, value)
        editor = subject.ToolkitUpdateMetadataStages()
        for first in (KeyboardInterrupt('first'), SystemExit('first'), Reject()):
            with patch.object(subject, '_verify_signature', side_effect=first):
                with self.assertRaises(type(first)) as observed:
                    editor.evaluate(encode(captured()), certificate_der=leaf(), at_utc=AT)
            self.assertIs(observed.exception, first)
            self.assertIs(editor.last_report.cause, first)
            result = rows(editor.last_report)
            self.assertEqual(result['canonicalization']['status'], 'passed')
            self.assertEqual(result['jwt_cryptographic_signature']['status'], 'not_run')
            self.assertEqual(result['jwt_lifetime']['status'], 'not_run')
            with self.assertRaises(ValueError): editor.evaluate(b'{}', certificate_der=b'x', at_utc='bad')
            self.assertIsNone(editor.last_report)

    def test_evidence_serialization_interruption_cannot_replace_original(self):
        first = KeyboardInterrupt('original crypto interruption')
        later = SystemExit('secondary JSON serialization')
        editor = subject.ToolkitUpdateMetadataStages()
        original_dumps = json.dumps
        def dumps(value, *args, **kwargs):
            if type(value) is dict and value.get('interrupted'):
                raise later
            return original_dumps(value, *args, **kwargs)
        raw = encode(captured()); certificate = leaf()
        with patch.object(subject, '_verify_signature', side_effect=first), patch.object(subject.json, 'dumps', side_effect=dumps):
            with self.assertRaises(KeyboardInterrupt) as observed:
                editor.evaluate(raw, certificate_der=certificate, at_utc=AT)
        self.assertIs(observed.exception, first)
        self.assertIs(editor.last_report.cause, first)
        value = editor.last_report.as_dict()
        self.assertTrue(value['evidence_serialization_failed'])
        self.assertEqual(value['input_node_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertFalse(editor.last_report.all_supported_stages_passed)

    def test_select_node_normalization_identity_duplicate_and_input_guards(self):
        raw = fixture()['raw_catalogue_json'].encode()
        node = captured()
        selected = subject.select_node(raw, node_id=node['nodeId'])
        self.assertEqual(json.loads(selected), node)
        self.assertTrue(self.evaluate(json.loads(selected)).all_supported_stages_passed)
        for response in ({'data':[node,node]}, {'data':[]}, {'data':[1]}):
            with self.assertRaises(ValueError): subject.select_node(encode(response), node_id=node['nodeId'])
        for identity in ('', True, 'x'*257, '\ud800'):
            with self.assertRaises(ValueError): subject.select_node(raw, node_id=identity)


if __name__ == '__main__': unittest.main()
