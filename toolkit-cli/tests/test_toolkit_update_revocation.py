import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from cbus_toolkit import toolkit_update_revocation as subject, toolkit_update_metadata as metadata
from tests.test_toolkit_update_metadata import (AT, NOW, encode, fixture as metadata_fixture,
    captured as metadata_node, leaf as metadata_leaf, owned_der)

FIXTURE = Path(__file__).resolve().parents[1]/'research/fixtures/toolkit-update-revocation-vectors.json'
CAPTURE_AT = '2026-09-15T04:04:00.1234567Z'


def fixture():
    return json.loads(FIXTURE.read_text())


def captured(name='leaf'):
    return json.loads(fixture()['raw_responses'][name])['data']


def signer():
    return base64.b64decode(next(x['der_base64'] for x in fixture()['certificates'] if x['id']=='signer'))


def rows(report):
    return {row['stage']:row for row in report.as_dict()['stages']}


def signed_list(*, data=None, claims=None, remove=(), header_changes=None, corrupt=False):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    value = copy.deepcopy(captured() if data is None else data)
    canonical, _ = subject._canonical(value)
    digest = base64.b64encode(hashlib.sha256(canonical).digest()).decode()
    payload = {'nbf':NOW-3600,'exp':NOW+3600,'iat':NOW-3600,'payload_sha256':digest}
    payload.update(claims or {})
    for name in remove:payload.pop(name, None)
    thumbprint = hashlib.sha1(owned_der()).hexdigest().upper()
    header = {'alg':'RS256','typ':'JWT','x5t':thumbprint,'kid':thumbprint,'pol':'rv1','crit':['pol']}
    header.update(header_changes or {})
    b64 = lambda raw:base64.urlsafe_b64encode(raw).rstrip(b'=')
    signing = b64(encode(header))+b'.'+b64(encode(payload))
    key = serialization.load_pem_private_key(metadata_fixture()['owned_test_key_pem'].encode(), None)
    signature = key.sign(signing,padding.PKCS1v15(),hashes.SHA256())
    if corrupt:signature=bytes((signature[0]^1,))+signature[1:]
    value['signatures']={'rv1':(signing+b'.'+b64(signature)).decode()}
    return value


class RevocationTests(unittest.TestCase):
    def evaluate(self, data=None, *, der=None, at=CAPTURE_AT, **kwargs):
        with patch('socket.socket',side_effect=AssertionError('No network')), patch('ssl.create_default_context',side_effect=AssertionError('No TLS/store')):
            return subject.ToolkitUpdateRevocationStages().evaluate(encode(captured() if data is None else data),
                signer_certificate_der=signer() if der is None else der,at_utc=at,**kwargs)

    def test_actual_two_rv1_signatures_and_pin_identity_preserve_raw_der(self):
        original = signer()
        for name in ('leaf','root'):
            result=self.evaluate(captured(name));self.assertTrue(result.all_supported_stages_passed)
            value=result.as_dict();observed=rows(result)
            self.assertEqual(observed['original_revocation_signer_identity']['matched_pin'],'85CAABAC10E725ED52593159E9B3E6AB5FFD70E2')
            self.assertTrue(observed['jwt_cryptographic_signature']['signature_valid_for_supplied_key'])
            self.assertEqual(value['signer_certificate_der_sha256'],hashlib.sha256(original).hexdigest())
            self.assertEqual(value['evaluation_ticks_100ns']%10000000,1234567)
            for field in ('publisher_trust','certificate_chain','complete_revocation_status','applicability'):
                self.assertEqual(value[field]['status'],'not_evaluated')
            for field in ('not_revoked','publisher_verified','metadata_verified','updates_available'):
                self.assertNotIn(field,value)
            self.assertFalse(value['claimed_lists']['request_subject_association_verified'])
            value['claimed_lists']['revoked_certificates'].append('forged')
            self.assertEqual(result.as_dict()['claimed_lists']['revoked_certificates'],[])
        self.assertEqual(signer(),original)

    def test_original_canonical_cases_have_exact_bytes_defaults_order_and_case(self):
        passed=[];unsupported=[]
        for case in fixture()['canonical_cases']:
            observed=rows(self.evaluate(json.loads(case['input_data_json'])))['canonicalization']
            if observed['status']=='passed':
                self.assertTrue(case['original']['completed'],case['id'])
                self.assertEqual(observed['canonical_utf8'],case['original']['canonical_json'],case['id'])
                self.assertEqual(observed['sha256_base64'],case['original']['digest'],case['id'])
                passed.append(case['id'])
            else:
                self.assertEqual(observed['status'],'unsupported',case['id']);unsupported.append(case['id'])
        self.assertEqual(len(passed),22)
        self.assertEqual(len(unsupported),21)
        for label in ('missing-revokedCertificates','null-revokedCertificates','missing-id'):
            self.assertIn('v1/'+label,passed)
        for label in ('duplicate-revokedCertificates','reversed-revokedSignatures','lowercase-revokedCertificates'):
            self.assertIn('v2/'+label,passed)

    def test_original_pin_map_and_all_three_native_raw_public_keys(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        self.assertEqual(dict(subject._SIGNER_PINS),fixture()['original_pin_maps']['revocation_signers'])
        for cert in fixture()['certificates']:
            raw=base64.b64decode(cert['der_base64']);key=x509.load_der_x509_certificate(raw).public_key()
            match,digest=subject._pin_identity(key,cert['thumbprint'])
            self.assertEqual(match,cert['id']=='signer')
            self.assertEqual(digest,hashlib.sha256(key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.PKCS1)).hexdigest())
        key=x509.load_der_x509_certificate(owned_der()).public_key()
        self.assertFalse(subject._pin_identity(key,'85CAABAC10E725ED52593159E9B3E6AB5FFD70E2')[0])

    def test_owned_signature_passes_crypto_but_never_historical_identity(self):
        data=captured();data['revokedCertificates']=[captured('root')['id'],data['id'],captured('root')['id']]
        data['revokedSignatures']=[captured('root')['signatures']['rv1'],data['signatures']['rv1']]
        signed=signed_list(data=data)
        observed=rows(self.evaluate(signed,der=owned_der(),at=AT))
        self.assertEqual(observed['original_revocation_signer_identity']['status'],'failed')
        for stage in ('certificate_identity','canonicalization','jwt_cryptographic_signature','jwt_lifetime','payload_digest_claim'):
            self.assertEqual(observed[stage]['status'],'passed')
        signed['revokedCertificates'].reverse()
        # The palindrome remains identical; deleting its duplicate changes the signed bytes.
        signed['revokedCertificates'].pop()
        changed=rows(self.evaluate(signed,der=owned_der(),at=AT))
        self.assertEqual(changed['jwt_cryptographic_signature']['status'],'passed')
        self.assertEqual(changed['payload_digest_claim']['status'],'failed')
        changed=rows(self.evaluate(signed_list(corrupt=True),der=owned_der(),at=AT))
        self.assertFalse(changed['payload_digest_claim']['claims_signature_valid_for_supplied_key'])
        self.assertEqual(changed['jwt_cryptographic_signature']['status'],'failed')

    def test_historical_identity_is_independent_of_x5t_and_signature_failures(self):
        data=captured();parts=data['signatures']['rv1'].split('.');parts[2]=('A' if parts[2][0]!='A' else 'B')+parts[2][1:]
        data['signatures']['rv1']='.'.join(parts)
        observed=rows(self.evaluate(data))
        self.assertEqual(observed['original_revocation_signer_identity']['status'],'passed')
        self.assertEqual(observed['jwt_cryptographic_signature']['status'],'failed')
        observed=rows(self.evaluate(signed_list(header_changes={'x5t':'0'*40}),der=owned_der(),at=AT))
        self.assertEqual(observed['certificate_identity']['status'],'failed')
        self.assertEqual(observed['jwt_cryptographic_signature']['status'],'passed')

    def test_exact_lifetime_ticks_missing_expiration_and_saturation(self):
        for changes,at,expected in [({'exp':NOW-300},AT,'passed'),({'exp':NOW-300},'2030-01-01T00:00:00.0000001Z','failed'),
                ({'nbf':NOW+300},AT,'passed'),({'nbf':NOW+300},'2029-12-31T23:59:59.9999999Z','failed'),
                ({'exp':9223372036854775807},AT,'passed'),({'nbf':NOW+7200},AT,'failed')]:
            result=rows(self.evaluate(signed_list(claims=changes),der=owned_der(),at=at))
            self.assertEqual(result['jwt_lifetime']['status'],expected)
        result=rows(self.evaluate(signed_list(remove=('exp',)),der=owned_der(),at=AT))
        self.assertEqual(result['jwt_lifetime']['reason'],'missing_expiration')

    def test_der_errors_and_missing_dependency_are_independent(self):
        self.assertEqual(rows(self.evaluate(der=b'not DER'))['certificate_identity']['status'],'failed')
        oid=bytes.fromhex('06092a864886f70d010101');raw=signer();self.assertEqual(raw.count(oid),1)
        observed=rows(self.evaluate(der=raw.replace(oid,oid[:-1]+b'\x63',1)))
        self.assertEqual(observed['certificate_identity']['status'],'unsupported')
        self.assertEqual(observed['original_revocation_signer_identity']['status'],'not_run')
        self.assertEqual(observed['payload_digest_claim']['status'],'passed')
        with patch.object(subject,'_load_certificate',side_effect=ImportError('missing')):
            self.assertEqual(rows(self.evaluate())['certificate_identity']['status'],'unsupported')

    def test_strict_bounds_precede_crypto_and_context_rejects_implicit_time(self):
        manager=subject.ToolkitUpdateRevocationStages()
        with patch.object(subject,'_load_certificate',side_effect=AssertionError('No crypto')):
            for raw in (b'{"id":1,"id":2}',b'{"x":'+b'9'*100000+b'}',b'{"x":NaN}',b'{"x":"\\ud800"}',b'['*33+b'0'+b']'*33,b'\xff',b' '*(subject.MAX_NODE_BYTES+1)):
                with self.assertRaises(ValueError):manager.evaluate(raw,signer_certificate_der=signer(),at_utc=AT)
            for context in ({'at_utc':None},{'at_utc':'2030-01-01T00:00:00+00:00'},{'at_utc':AT,'culture':'en'},{'at_utc':AT,'timezone':'local'}):
                with self.assertRaises(ValueError):manager.evaluate(b'{}',signer_certificate_der=signer(),**context)
        for value in ([captured()['id']]*(subject.MAX_LIST_ENTRIES+1),['2026-09-15T01:02:03Z'],[None],[42]):
            data=captured();data['revokedCertificates']=value
            self.assertEqual(rows(self.evaluate(data))['canonicalization']['status'],'unsupported')
        data=captured();data['signatures']['rv1']=signed_list(header_changes={'pol':'v1'})['signatures']['rv1']
        self.assertEqual(rows(self.evaluate(data))['jwt_parsing']['status'],'unsupported')

    def test_response_selection_is_normalized_strict_and_keeps_unknown_data_visible(self):
        raw=fixture()['raw_responses']['leaf'].encode();selected=subject.select_revocation_data(raw)
        self.assertEqual(json.loads(selected),captured());self.assertNotEqual(raw,selected)
        for values in ({'success':1},{'success':False},{'statusCode':True},{'statusCode':201},{'data':None}):
            response=json.loads(raw);response.update(values)
            with self.assertRaises(ValueError):subject.select_revocation_data(encode(response))
        response=json.loads(raw);response['data']['unknown']={}
        observed=rows(self.evaluate(json.loads(subject.select_revocation_data(encode(response)))))
        self.assertEqual(observed['canonicalization']['status'],'unsupported')

    def test_first_interrupt_survives_serialization_attachment_and_stale_report(self):
        class Refuse(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name=='toolkit_update_revocation_evidence':raise SystemExit('attachment')
                super().__setattr__(name,value)
        for first in (Refuse('first'),SystemExit('first')):
            manager=subject.ToolkitUpdateRevocationStages();later=SystemExit('later')
            original=subject.json.dumps
            def dumps(value,*args,**kwargs):
                if type(value)is dict and value.get('interrupted'):raise later
                return original(value,*args,**kwargs)
            with patch.object(subject,'_verify_signature',side_effect=first),patch.object(subject.json,'dumps',side_effect=dumps):
                with self.assertRaises(type(first)) as observed:manager.evaluate(encode(captured()),signer_certificate_der=signer(),at_utc=AT)
            self.assertIs(observed.exception,first);self.assertIs(manager.last_report.cause,first)
            evidence=manager.last_report.as_dict();self.assertTrue(evidence['evidence_serialization_failed'])
            self.assertEqual(evidence['input_revocation_sha256'],hashlib.sha256(encode(captured())).hexdigest())
            with self.assertRaises(ValueError):manager.evaluate(b'{}',signer_certificate_der=signer(),at_utc=None)
            self.assertIsNone(manager.last_report)

    def test_existing_v1_all_seven_fixed_reports_and_error_strings_are_unchanged(self):
        baseline=fixture()['metadata_fixed_reports']
        for index,expected in enumerate(baseline):
            node=metadata_node(index)
            actual=metadata.ToolkitUpdateMetadataStages().evaluate(encode(node),certificate_der=metadata_leaf(),at_utc='2026-09-15T02:34:07.1234567Z')
            self.assertEqual(actual.as_dict(),expected['report'])
        with self.assertRaisesRegex(ValueError,'A nonempty signatures.v1 compact JWT is required'):metadata._token({})
        node=metadata_node();node['signatures']['v1']=captured()['signatures']['rv1']
        with self.assertRaisesRegex(ValueError,'outside the known v1 shape'):metadata._token(node)
        with self.assertRaises(ValueError):metadata._token(node,policy='unreviewed')


if __name__=='__main__':unittest.main()
