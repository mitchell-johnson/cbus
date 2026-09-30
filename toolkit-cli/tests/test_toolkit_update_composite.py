import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cbus_toolkit import cli
from cbus_toolkit.toolkit_update_composite import compose_update_report
from cbus_toolkit.toolkit_update_metadata import _canonical
from tests.test_toolkit_update_download import catalogue_report
from tests.update_trust_pki import AT, VALID, Chain, encode, key, sign_token

ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / 'research/fixtures/toolkit-update-metadata-vectors.json'
NODE_ID = '2398558e-aa7e-4777-b4a8-f1e8f21704ea'
ROLES = {'root': {}, 'leaf': {'issuer': 'root'}, 'signer': {}, 'other': {}, 'other_leaf': {'issuer': 'other'}}


def captured_node():
    nodes = json.loads(json.loads(METADATA.read_text())['raw_catalogue_json'])['data']
    return copy.deepcopy(next(node for node in nodes if node['nodeId'] == NODE_ID))


def signed(node, chain, *, leaf='leaf', lifetime=VALID):
    try:
        digest = base64.b64encode(hashlib.sha256(_canonical(node)).digest()).decode()
    except ValueError:  # Outside the canonical metadata domain; metadata reports unsupported.
        digest = 'outside-canonical-domain'

    node['signatures'] = {'v1': sign_token(key(leaf), chain.thumbprint(leaf), 'v1', digest, lifetime)}
    return node


def response(*nodes):
    return json.dumps({'success': True, 'statusCode': 200, 'message': 'owned', 'data': list(nodes)},
                      separators=(',', ':')).encode()


class CompositeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain = Chain(ROLES)
        cls.expired = Chain({**ROLES, 'leaf': {'issuer': 'root', 'window': (-30, -1)}})

    def inputs(self, *, node=None, chain=None, revoked=(), anchors=True, **overrides):
        chain = chain or self.chain
        node = signed(node or captured_node(), chain)
        body = response(node)
        values = dict(catalogue_report=catalogue_report(body), catalogue_response=body, node_id=NODE_ID, file_id='5',
                      platform='windows_x86_64', at_utc=AT, leaf_der=chain.der['leaf'], issuer_ders=[chain.der['root']],
                      revocation_lists=[chain.revocation_list('leaf'),
                                        chain.revocation_list('root', revoked_certificates=revoked)],
                      revocation_signer_ders=[chain.der['signer']],
                      anchors=chain.anchors() if anchors else None)
        values.update(overrides)
        return values

    def report(self, **kwargs):
        return compose_update_report(**self.inputs(**kwargs)).as_dict()

    def stages(self, report):
        return {row['stage']: row for row in report['stages']}

    def test_same_source_inputs_are_download_eligible_without_network(self):
        report = self.report()
        self.assertEqual(report['status'], 'eligible', json.dumps(report, indent=1))
        self.assertTrue(report['download_eligible_under_supplied_evidence'])
        self.assertTrue(all(row['matched'] for row in report['source_bindings']))
        self.assertEqual([row['status'] for row in report['stages']], ['passed'] * 7)
        for name in ('network_request_initiated', 'downloaded', 'installed', 'install_permitted',
                     'current_publisher_trust_established'):
            self.assertFalse(report[name])
        self.assertIsNone(report['updates_available'])

    def test_leaf_from_another_chain_is_refused(self):
        other = self.chain
        report = self.report(leaf_der=other.der['other_leaf'], issuer_ders=[other.der['other']])
        self.assertEqual(report['status'], 'refused')
        self.assertIn({'binding': 'metadata_x5t_names_supplied_leaf', 'matched': False}, report['source_bindings'])
        self.assertFalse(report['download_eligible_under_supplied_evidence'])

    def test_catalogue_report_from_another_response_fails_before_later_stages(self):
        other = response(signed(captured_node(), self.chain, lifetime={'nbf': -10, 'exp': 10}))
        report = self.report(catalogue_report=catalogue_report(other))
        self.assertEqual(self.stages(report)['catalogue']['status'], 'failed')
        self.assertEqual(self.stages(report)['metadata']['status'], 'not_run')
        self.assertEqual(report['status'], 'failed')

    def test_expired_leaf_revoked_leaf_and_wrong_anchor_fail(self):
        expired = self.report(chain=self.expired)
        self.assertEqual(self.stages(expired)['trust']['status'], 'failed')
        self.assertEqual(self.stages(expired)['trust']['chain_status'], ['NotTimeValid', 'UntrustedRoot'])
        revoked = self.report(revoked=('leaf',))
        self.assertEqual(self.stages(revoked)['revocation']['traversal_reason'], 'certificate_revoked')
        wrong = self.report(anchors=False)
        self.assertEqual(self.stages(wrong)['revocation']['traversal_reason'], 'revocation_signer_not_pinned')
        for report in (expired, revoked, wrong):
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(self.stages(report)['download_eligibility']['status'], 'failed')

    def test_file_not_selected_by_applicability_is_refused(self):
        node = captured_node()
        extra = copy.deepcopy(node['files'][0])
        extra.update(id='6', metadata={'architecture': 'windows_x86_32', 'mediatype': 'singleFileExecutable'})
        node['files'].append(extra)
        node['urls']['6'] = {'url': extra['url']}
        report = self.report(node=node, file_id='6')
        self.assertEqual(report['status'], 'refused')
        self.assertIn({'binding': 'applicability_selected_file_is_download_file', 'matched': False},
                      report['source_bindings'])

    def test_selected_uri_must_equal_bound_download_url(self):
        node = captured_node()
        node['urls']['5'] = {'url': 'https://mirror.invalid/other/Setup.exe'}
        report = self.report(node=node)
        self.assertEqual(report['status'], 'refused')
        self.assertIn({'binding': 'selected_uri_is_download_url', 'matched': False}, report['source_bindings'])

    def test_nonempty_conditions_use_supplied_facts_from_the_same_node(self):
        node = captured_node()
        node['data']['clientConditionData'] = {'expression': 'current', 'conditions': {'current': {
            'whatToCheck': 'fileVersion', 'howToCheck': 'isLess', 'fileOrRegistryKeyPath': 'C:\\Apps\\Toolkit.exe',
            'comparisonRightSideValue': '1.18.1'}}}
        def context(version):
            return encode({'format': 'cbus-toolkit-condition-context-v1', 'culture': 'invariant-ascii',
                           'files': [{'path': 'C:\\Apps\\Toolkit.exe', 'exists': True, 'file_version': version}]})
        passed = self.report(node=copy.deepcopy(node), condition_context=context(' 1.18.0.2754'))
        self.assertEqual(self.stages(passed)['conditions']['status'], 'passed')
        self.assertEqual(self.stages(passed)['applicability']['status'], 'passed')
        self.assertTrue(self.stages(passed)['applicability']['checks']['nonempty_conditions_under_supplied_facts'])
        # Signed canonical serialization of nonempty Condition models is not recovered yet.
        self.assertEqual(self.stages(passed)['metadata']['stages']['canonicalization'], 'unsupported')
        self.assertEqual(passed['status'], 'unsupported')
        failed = self.report(node=copy.deepcopy(node), condition_context=context('1.18.1.0'))
        self.assertEqual(self.stages(failed)['conditions']['status'], 'failed')
        self.assertEqual(self.stages(failed)['applicability']['status'], 'failed')
        self.assertEqual(failed['status'], 'failed')
        unsupported = self.report(node=copy.deepcopy(node))
        self.assertEqual(unsupported['status'], 'unsupported')

    def test_cli_uses_one_input_set(self):
        values = self.inputs()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            def write(name, data):
                (folder / name).write_bytes(data)
                return str(folder / name)
            argv = ['update-composite-report', '--catalogue-report', write('report.json', values['catalogue_report']),
                    '--catalogue-response', write('response.json', values['catalogue_response']),
                    '--node-id', NODE_ID, '--file-id', '5', '--platform', 'windows_x86_64', '--at-utc', AT,
                    '--leaf-certificate', write('leaf.der', values['leaf_der']),
                    '--issuer-certificate', write('root.der', values['issuer_ders'][0]),
                    '--revocation-list', write('leaf-list.json', values['revocation_lists'][0]),
                    '--revocation-list', write('root-list.json', values['revocation_lists'][1]),
                    '--revocation-signer', write('signer.der', values['revocation_signer_ders'][0]),
                    '--anchor-root-certificate', str(folder / 'root.der'),
                    '--anchor-revocation-signer', str(folder / 'signer.der')]
            result, status = cli.run(cli.build_parser().parse_args(argv))
            self.assertEqual((result['status'], status), ('eligible', 0))
            trust, trust_status = cli.run(cli.build_parser().parse_args(
                ['update-trust', '--leaf-certificate', str(folder / 'leaf.der'),
                 '--issuer-certificate', str(folder / 'root.der'),
                 '--revocation-list', str(folder / 'leaf-list.json'), '--revocation-list', str(folder / 'root-list.json'),
                 '--revocation-signer', str(folder / 'signer.der'), '--at-utc', AT,
                 '--anchor-root-certificate', str(folder / 'root.der'),
                 '--anchor-revocation-signer', str(folder / 'signer.der')]))
            self.assertEqual((trust['status'], trust_status), ('passed', 0))
            default, default_status = cli.run(cli.build_parser().parse_args(
                ['update-trust', '--leaf-certificate', str(folder / 'leaf.der'),
                 '--issuer-certificate', str(folder / 'root.der'),
                 '--revocation-list', str(folder / 'leaf-list.json'), '--revocation-list', str(folder / 'root-list.json'),
                 '--revocation-signer', str(folder / 'signer.der'), '--at-utc', AT]))
            self.assertEqual((default['status'], default_status), ('failed', 1))


if __name__ == '__main__':
    unittest.main()
