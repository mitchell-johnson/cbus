import base64
import json
from pathlib import Path
import unittest

from cbus_toolkit.toolkit_update_trust import (TrustInputError, anchor_pins_from_certificates,
                                               evaluate_update_trust, load_anchor_profile)
from tests.update_trust_pki import AT, Chain, lists

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / 'research/fixtures/toolkit-update-trust-original.json'
REVOCATION = ROOT / 'research/fixtures/toolkit-update-revocation-vectors.json'
METADATA = ROOT / 'research/fixtures/toolkit-update-metadata-vectors.json'
CAPTURE_AT = '2026-09-15T04:04:00Z'
NODE_TOKEN = 'eyJhbGciOiJSUzI1NiJ9.eyJzeW50aGV0aWMiOnRydWV9.c3ludGhldGlj'

# Original traversal messages mapped to this stage's reason codes.
REASONS = {
    'selfsigned without being a CA': 'self_signed_certificate_not_pinned',
    'contains revoked certificate': 'certificate_revoked',
    'is not trusted': 'revocation_signer_not_pinned',
    "is missing signature 'rv1'": 'revocation_list_missing_rv1',
    'IDX10223': 'revocation_token_expired',
    'longer than max chain length': 'chain_longer_than_maximum',
}
# Deliberate admission rule: a supplied list is bound to its certificate by id.
ADMISSION_DIVERGENCE = {'revocation-list-id-mismatch': 'revocation_list_not_supplied'}


def original_cases():
    return [row for row in json.loads(ORIGINAL.read_text())['cases'] if row['stage'] == 'original-trust-case']


def run_case(case):
    chain = Chain(case['roles'])
    token = NODE_TOKEN
    documents = [chain.revocation_list(row['for'], signer=row['signer'], signed=row['signed'],
                                       lifetime=row['lifetime'], revoked_certificates=row['revoked_certificates'],
                                       revoked_signatures=row['revoked_signatures'], id=row.get('id'), node_token=token)
                 for row in case['revocation_lists']]
    issuers = [chain.der[name] for name in case['roles'] if name != case['leaf'] and name != 'signer'
               and name != 'other']
    report = evaluate_update_trust(leaf_der=chain.der[case['leaf']], issuer_ders=issuers, revocation_lists=documents,
                                   revocation_signer_ders=[chain.der['signer']], at_utc=AT,
                                   anchors=chain.anchors(case['pin_roots'], case['pin_signers']), node_token=token)
    return report.as_dict()


def stage(report, name):
    return next(row for row in report['stages'] if row['stage'] == name)


class OriginalDifferentialTests(unittest.TestCase):
    def test_every_retained_original_case(self):
        cases = original_cases()
        self.assertEqual(len(cases), 27)
        for row in cases:
            with self.subTest(case=row['label']):
                report = run_case(row['case'])
                traversal = stage(report, 'original_traversal')
                original = row['original_traversal']
                if row['label'] in ADMISSION_DIVERGENCE:
                    self.assertTrue(original['accepted'])
                    self.assertEqual(traversal['reason'], ADMISSION_DIVERGENCE[row['label']])
                    continue
                if not original['accepted']:
                    self.assertEqual(traversal['status'], 'failed')
                    expected = next(code for text, code in REASONS.items() if text in original['message'])
                    self.assertEqual(traversal['reason'], expected)
                    self.assertFalse(report['trusted_under_supplied_anchor_profile'])
                    continue
                self.assertEqual(traversal['status'], 'passed')
                self.assertEqual(stage(report, 'node_signature_revocation')['node_token_revoked'],
                                 original['node_token_revoked'])
                if original['node_token_revoked']:
                    self.assertEqual(report['status'], 'failed')
                    continue
                built = row['x509_chain_with_original_policy']
                policy = stage(report, 'chain_policy')
                self.assertEqual(policy['chain_status'], built['chain_status'])
                self.assertEqual(policy['status'] == 'passed', built['built'])
                expired_node = row['label'] == 'node-token-expired'  # rejected by metadata jwt_lifetime instead
                self.assertEqual(report['trusted_under_supplied_anchor_profile'],
                                 row['original_is_metadata_validated'] or expired_node)


class CapturedProductChainTests(unittest.TestCase):
    def inputs(self):
        data = json.loads(REVOCATION.read_text())
        certificates = {row['id']: base64.b64decode(row['der_base64']) for row in data['certificates']}
        lists = [data['raw_responses'][name].encode() for name in ('leaf', 'root')]
        node = json.loads(json.loads(METADATA.read_text())['raw_catalogue_json'])['data'][0]
        return certificates, lists, node['signatures']['v1']

    def test_captured_chain_passes_embedded_profile_like_original(self):
        certificates, documents, token = self.inputs()
        report = evaluate_update_trust(leaf_der=certificates['leaf'], issuer_ders=[certificates['root']],
                                       revocation_lists=documents, revocation_signer_ders=[certificates['signer']],
                                       at_utc=CAPTURE_AT, node_token=token).as_dict()
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['anchor_profile']['id'], 'sesu-3.0.7-embedded-whitelistcert')
        self.assertFalse(report['current_publisher_trust_established'])
        self.assertFalse(report['network_accessed'])

    def test_captured_chain_fails_after_certificate_expiry_and_under_other_anchors(self):
        certificates, documents, token = self.inputs()
        expired = evaluate_update_trust(leaf_der=certificates['leaf'], issuer_ders=[certificates['root']],
                                        revocation_lists=documents, revocation_signer_ders=[certificates['signer']],
                                        at_utc='2034-06-01T00:00:00Z', node_token=token).as_dict()
        self.assertEqual(expired['status'], 'failed')
        self.assertIn(stage(expired, 'original_traversal')['reason'], ('revocation_token_expired',))
        synthetic = Chain({'root': {}, 'signer': {}})
        other = evaluate_update_trust(leaf_der=certificates['leaf'], issuer_ders=[certificates['root']],
                                      revocation_lists=documents, revocation_signer_ders=[certificates['signer']],
                                      at_utc=CAPTURE_AT, anchors=synthetic.anchors(), node_token=token).as_dict()
        self.assertEqual(stage(other, 'original_traversal')['reason'], 'revocation_signer_not_pinned')


class AnchorAndInputTests(unittest.TestCase):
    def test_anchor_pins_derive_from_runtime_certificates(self):
        chain = Chain({'root': {}, 'signer': {}})
        raw = anchor_pins_from_certificates(roots=[chain.der['root']], revocation_signers=[chain.der['signer']])
        profile, digest = load_anchor_profile(raw)
        self.assertEqual(profile['roots'][0]['thumbprint_sha1'], chain.thumbprint('root'))
        self.assertEqual(profile['roots'][0]['public_key_sha256'], chain.public_key_sha256('root'))
        self.assertEqual(len(digest), 64)

    def test_malformed_anchor_profiles_and_duplicate_inputs_are_rejected(self):
        for raw in (b'{}', b'{"format":"x","roots":[],"revocation_signers":[]}',
                    b'{"format":"cbus-toolkit-update-trust-anchors-v1","roots":[{"thumbprint_sha1":"ab",'
                    b'"public_key_sha256":"00"}],"revocation_signers":[]}'):
            with self.subTest(raw=raw), self.assertRaises(TrustInputError):
                load_anchor_profile(raw)
        chain = Chain({'root': {}, 'leaf': {'issuer': 'root'}, 'signer': {}})
        documents = [chain.revocation_list('leaf'), chain.revocation_list('leaf')]
        with self.assertRaises(TrustInputError):
            evaluate_update_trust(leaf_der=chain.der['leaf'], issuer_ders=[chain.der['root']], revocation_lists=documents,
                                  revocation_signer_ders=[chain.der['signer']], at_utc=AT, anchors=chain.anchors())

    def test_unbound_inputs_and_missing_lists_fail_closed(self):
        chain = Chain({'root': {}, 'leaf': {'issuer': 'root'}, 'extra': {}, 'signer': {}})
        base = dict(leaf_der=chain.der['leaf'], revocation_signer_ders=[chain.der['signer']], at_utc=AT,
                    anchors=chain.anchors())
        missing = evaluate_update_trust(issuer_ders=[chain.der['root']],
                                        revocation_lists=[chain.revocation_list('leaf')], **base).as_dict()
        self.assertEqual(stage(missing, 'original_traversal')['reason'], 'revocation_list_not_supplied')
        extra = evaluate_update_trust(issuer_ders=[chain.der['root'], chain.der['extra']],
                                      revocation_lists=[chain.revocation_list('leaf'), chain.revocation_list('root')],
                                      **base).as_dict()
        self.assertEqual(stage(extra, 'original_traversal')['reason'], 'unbound_supplied_input')
        no_token = evaluate_update_trust(issuer_ders=[chain.der['root']],
                                         revocation_lists=[chain.revocation_list('leaf'), chain.revocation_list('root')],
                                         **base).as_dict()
        self.assertEqual(no_token['status'], 'passed')
        self.assertFalse(no_token['node_signature_revocation_evaluated'])

    def test_tampered_revocation_list_and_signature_fail(self):
        chain = Chain({'root': {}, 'leaf': {'issuer': 'root'}, 'signer': {}})
        tampered = json.loads(chain.revocation_list('leaf'))
        tampered['revokedSignatures'] = ['a.b.c']
        report = evaluate_update_trust(leaf_der=chain.der['leaf'], issuer_ders=[chain.der['root']],
                                       revocation_lists=[json.dumps(tampered).encode(), chain.revocation_list('root')],
                                       revocation_signer_ders=[chain.der['signer']], at_utc=AT,
                                       anchors=chain.anchors()).as_dict()
        self.assertEqual(stage(report, 'original_traversal')['reason'], 'revocation_payload_digest_mismatch')


if __name__ == '__main__':
    unittest.main()
