"""One same-source SESU update report: catalogue to download eligibility.

Every stage consumes the same caller-supplied input set: one catalogue report
and its exact response, one selected node and file, one signing chain with its
signed revocation lists, one anchor profile, one explicit UTC instant, one
platform and optional supplied condition facts and stored cohort. Each stage's
own source digests are compared with the catalogue selection; any
cross-source mismatch refuses the whole report.

The report never fetches, downloads, installs, reads the registry or consults
a clock. ``download_eligible_under_supplied_evidence`` is a calculation from
the supplied evidence, not a claim that the original Windows client would
offer or download the update now.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from .toolkit_update_applicability import inspect_update_applicability
from .toolkit_update_conditions import ToolkitUpdateConditions
from .toolkit_update_download import UpdateDownloadError, bind_download_source
from .toolkit_update_metadata import _Domain, _encode, _json, select_node, validate_context, validate_node_id
from .toolkit_update_metadata import ToolkitUpdateMetadataStages
from .toolkit_update_trust import TrustInputError, evaluate_update_trust

FORMAT = 'cbus-toolkit-update-composite-v1'
STAGES = ('catalogue', 'metadata', 'revocation', 'conditions', 'applicability', 'trust', 'download_eligibility')


@dataclass(frozen=True)
class CompositeReport:
    _document: str = field(repr=False)

    def as_dict(self):
        return json.loads(self._document)

    @property
    def status(self):
        return self.as_dict()['status']


def compose_update_report(*, catalogue_report: bytes, catalogue_response: bytes, node_id: str, file_id: str,
                          platform: str, at_utc: str, leaf_der: bytes, issuer_ders=(), revocation_lists=(),
                          revocation_signer_ders=(), anchors=None, condition_context=None,
                          stored_cohort=None) -> CompositeReport:
    validate_node_id(node_id)
    _, at_text = validate_context(at_utc)
    response_sha256 = hashlib.sha256(catalogue_response).hexdigest()
    document = {
        'format': FORMAT,
        'scope': 'One supplied input set evaluated through every SESU stage; no fetch, download, install or registry',
        'inputs': {'catalogue_report_sha256': hashlib.sha256(catalogue_report).hexdigest(),
                   'catalogue_response_sha256': response_sha256, 'node_id': node_id, 'file_id': file_id,
                   'platform': platform, 'at_utc': at_text,
                   'leaf_certificate_sha256': hashlib.sha256(leaf_der).hexdigest(),
                   'issuer_certificate_sha256': [hashlib.sha256(x).hexdigest() for x in issuer_ders],
                   'revocation_list_sha256': [hashlib.sha256(x).hexdigest() for x in revocation_lists],
                   'revocation_signer_sha256': [hashlib.sha256(x).hexdigest() for x in revocation_signer_ders],
                   'anchor_profile_sha256': None if anchors is None else hashlib.sha256(anchors).hexdigest(),
                   'condition_context_sha256': None if condition_context is None else hashlib.sha256(condition_context).hexdigest(),
                   'stored_cohort': stored_cohort},
        'stages': [{'stage': name, 'status': 'not_run'} for name in STAGES],
        'source_bindings': [],
        'status': None, 'download_eligible_under_supplied_evidence': False,
        'network_request_initiated': False, 'downloaded': False, 'installed': False, 'install_permitted': False,
        'registry_accessed': False, 'certificate_store_accessed': False, 'updates_available': None,
        'current_publisher_trust_established': False,
    }
    rows = {row['stage']: row for row in document['stages']}

    def bind(name, left, right):
        document['source_bindings'].append({'binding': name, 'matched': left == right})
        return left == right

    def finish():
        refused = not all(row['matched'] for row in document['source_bindings'])
        statuses = [row['status'] for row in document['stages']]
        if refused:
            document['status'] = 'refused'
        elif 'failed' in statuses:
            document['status'] = 'failed'
        elif rows['download_eligibility']['status'] == 'passed':
            document['status'] = 'eligible'
        else:
            document['status'] = 'unsupported'
        document['download_eligible_under_supplied_evidence'] = document['status'] == 'eligible'
        return CompositeReport(json.dumps(document, ensure_ascii=True, allow_nan=False))

    # 1. Catalogue: report reproduces from the exact response; unique node/file; bound HTTPS URL.
    source = None
    try:
        source = bind_download_source(catalogue_report, catalogue_response, node_id=node_id, file_id=file_id)
    except _Domain as error:
        # The signed model is outside the canonical domain; later stages remain diagnostic only.
        rows['catalogue'].update(status='unsupported', reason=str(error))
    except (UpdateDownloadError, ValueError) as error:
        rows['catalogue'].update(status='failed', reason=str(error))
        return finish()
    try:
        selected = select_node(catalogue_response, node_id=node_id)
    except ValueError as error:
        rows['catalogue'].update(status='failed', reason=str(error))
        return finish()
    node = _json(selected)
    selected_sha256 = hashlib.sha256(selected).hexdigest()
    if source is not None:
        rows['catalogue'].update(status='passed', selected_node_sha256=selected_sha256,
                                 canonical_node_sha256=source.provenance['canonical_node_sha256'],
                                 declared_size=source.declared_size, declared_sha1=source.declared_sha1,
                                 catalogue_claims_trusted=False)
        bind('catalogue_report_describes_response', source.provenance['catalogue_response_sha256'], response_sha256)
        bind('catalogue_selection', source.provenance['selected_node_sha256'], selected_sha256)

    # 2. Metadata: six signed-node stages against the supplied leaf.
    metadata = ToolkitUpdateMetadataStages().evaluate(selected, certificate_der=leaf_der, at_utc=at_text).as_dict()
    metadata_rows = {row['stage']: row['status'] for row in metadata['stages']}
    status = ('passed' if all(v == 'passed' for v in metadata_rows.values()) else
              'failed' if 'failed' in metadata_rows.values() else 'unsupported')
    rows['metadata'].update(status=status, stages=metadata_rows)
    bind('metadata_node', metadata['input_node_sha256'], selected_sha256)
    bind('metadata_x5t_names_supplied_leaf', metadata_rows.get('certificate_identity'), 'passed')
    token = (node.get('signatures') or {}).get('v1')

    # 3 and 6. Revocation traversal and chain policy from one trust evaluation.
    try:
        trust = evaluate_update_trust(leaf_der=leaf_der, issuer_ders=issuer_ders, revocation_lists=revocation_lists,
                                      revocation_signer_ders=revocation_signer_ders, at_utc=at_text, anchors=anchors,
                                      node_token=token if type(token) is str else None).as_dict()
    except (TrustInputError, ValueError) as error:
        rows['revocation'].update(status='failed', reason=str(error))
        return finish()
    trust_rows = {row['stage']: row for row in trust['stages']}
    traversal, node_revocation = trust_rows['original_traversal'], trust_rows['node_signature_revocation']
    rows['revocation'].update(
        status=('failed' if 'failed' in (traversal['status'], node_revocation['status']) else
                'passed' if (traversal['status'], node_revocation['status']) == ('passed', 'passed') else 'unsupported'),
        traversal=traversal['status'], traversal_reason=traversal.get('reason'),
        node_signature_revocation=node_revocation['status'])
    bind('trust_leaf_is_metadata_certificate', trust['certificates'][0]['der_sha256'],
         metadata.get('certificate_der_sha256'))
    bind('trust_node_token', trust['node_token_sha256'],
         hashlib.sha256(token.encode()).hexdigest() if type(token) is str else None)

    # 4. Conditions from this node's own clientConditionData.
    data = node.get('data') if type(node.get('data')) is dict else {}
    conditions = data.get('clientConditionData')
    condition_result = None
    if type(conditions) is not dict or type(conditions.get('conditions')) is not dict:
        rows['conditions'].update(status='unsupported', reason='node lacks a clientConditionData dictionary')
    elif not conditions['conditions']:
        rows['conditions'].update(status='passed', evaluated=False,
                                  reason='empty condition dictionary; the original skips evaluation')
    elif not conditions.get('expression'):
        rows['conditions'].update(status='unsupported',
                                  reason='nonempty conditions without an expression need unrecovered original synthesis')
    elif condition_context is None:
        rows['conditions'].update(status='unsupported', reason='nonempty conditions need a supplied condition context')
    else:
        condition_bytes = _encode(conditions)
        report = ToolkitUpdateConditions().evaluate(condition_bytes, context=condition_context).as_dict()
        condition_result = report['condition_result_under_supplied_context']
        rows['conditions'].update(
            status={True: 'passed', False: 'failed'}.get(condition_result, 'unsupported'), evaluated=True,
            result_under_supplied_facts=condition_result, context_verified=False)
        bind('conditions_from_selected_node', report.get('conditions_sha256'),
             hashlib.sha256(condition_bytes).hexdigest())

    # 5. Applicability on the same response, node, platform, instant and cohort.
    try:
        applicability = inspect_update_applicability(
            catalogue_response, node_id=node_id, platform=platform, at_utc=at_text, stored_cohort=stored_cohort,
            condition_result=condition_result if rows['conditions'].get('evaluated') else None).as_dict()
    except ValueError as error:
        rows['applicability'].update(status='failed', reason=str(error))
        return finish()
    rows['applicability'].update(status=applicability['status'], reason=applicability['reason'],
                                 selected_file_id=applicability['selected_file_id'], checks=applicability['checks'])
    bind('applicability_response', applicability['catalogue_source_sha256'], response_sha256)
    bind('applicability_node', applicability['selected_node_sha256'], selected_sha256)
    if applicability['selected_file_id'] is not None:
        bind('applicability_selected_file_is_download_file', applicability['selected_file_id'], file_id)
    urls = node.get('urls') if type(node.get('urls')) is dict else {}
    selected_uri = (urls.get(file_id) or {}).get('url') if type(urls.get(file_id)) is dict else None
    if source is not None:
        bind('selected_uri_is_download_url', selected_uri, source.url)

    # 6. Anchor profile and X509Chain policy.
    policy = trust_rows['chain_policy']
    rows['trust'].update(status=policy['status'] if traversal['status'] == 'passed' else 'not_run',
                         anchor_profile=trust['anchor_profile'], chain_status=policy.get('chain_status'),
                         trusted_under_supplied_anchor_profile=trust['trusted_under_supplied_anchor_profile'])

    # 7. Eligibility only; nothing is fetched.
    prior = [rows[name]['status'] for name in STAGES[:-1]]
    if all(value == 'passed' for value in prior) and source is not None:
        rows['download_eligibility'].update(status='passed', url_host=source.host, output_file_name=source.file_name,
                                            declared_size=source.declared_size, network_request_initiated=False)
    else:
        rows['download_eligibility'].update(
            status='failed' if 'failed' in prior else 'not_run',
            reason='every earlier stage must pass under the same supplied evidence')
    return finish()
