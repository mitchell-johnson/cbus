"""Lazy conditions with explicit registry observations and supplied file facts.

This additive wrapper leaves the supplied-context v1/v2 reports unchanged. It
does not establish package applicability, publisher trust or update availability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from . import toolkit_update_conditions as core
from . import _toolkit_update_registry_conditions as leaves
from .toolkit_update_metadata import _error
from .windows_condition_registry import WindowsConditionRegistry

PROFILE = 'toolkit-1.18-sesu-3.0.7-lazy-registry-observations-v1'


@dataclass(frozen=True)
class LiveConditionReport:
    _document: str = field(repr=False)
    cause: BaseException | None = field(default=None, repr=False, compare=False)
    result: bool | None = field(default=None, repr=False)

    @property
    def computed(self):
        # A report that also carries a failure cause (for example a
        # close-time provider error after a successful evaluation) read as
        # computed-yet-raised; only a clean boolean result counts.
        return type(self.result) is bool and self.cause is None

    def as_dict(self):
        return json.loads(self._document)


class _LiveFacts:
    """One mapping read per uncached leaf; there is deliberately no query cache.

    Membership is structural, not observational: a well-formed registry-leaf
    key (path/entry/default triple of the documented shapes) is always
    present because its value can only be known by asking the provider, so
    probing it must trigger exactly one observation. Malformed keys report
    absent so they cannot consume the bounded observation budget. Genuine
    over-probing still stops at eight observations with an explicit
    unsupported domain outcome via the shared core.
    """
    def __init__(self, observer, document):
        self.observer = observer
        self.document = document

    def __contains__(self, key):
        return (type(key) is tuple and len(key) == 3
                and type(key[0]) is str and type(key[1]) is str
                and type(key[2]) is tuple and len(key[2]) == 2)

    def __getitem__(self, key):
        rows = self.document['registry_observations']
        if len(rows) >= 8:
            core._unsupported('At most eight live registry leaf observations are supported')
        if not self.document['events']:
            core._unsupported('Registry observation requires an active condition evaluation event')
        query = {'path': key[0], 'entry': key[1], 'default': {'kind': key[2][0], 'value': key[2][1]}}
        event = self.document['events'][-1]
        row = {'sequence': len(rows), 'lookup_name': event['lookup_name'], 'query': query,
               'status': 'requesting', 'provider_identity_verified': False}
        rows.append(row)
        event['registry_observation_sequence'] = row['sequence']
        try:
            result = self.observer.read({'path': query['path'], 'entry': query['entry'], 'default': dict(query['default'])})
            if type(self.observer) is WindowsConditionRegistry:
                receipt = self.observer._validate_observation(result)
                if receipt['query'] != query or receipt['sequence'] != row['sequence']:
                    raise ValueError('Registry observation does not belong to this fresh evaluation sequence')
                result = receipt['result']
                row.update(provider_identity_verified=True, source='checked_framework_worker', receipt=receipt)
            else:
                row.update(source='unverified_external_provider')
            value = leaves._primitive(result)
            row.update(status='observed', result={'kind': value[0], 'value': value[1]})
            return value
        except BaseException as error:
            try:
                row.update(status='failed', error=_error(error))
            except BaseException:
                row['error_export_failed'] = True
            raise


class ToolkitLiveUpdateConditions:
    """Evaluate once with a fresh observer; no registry access during validation.

    WindowsConditionRegistry receipts carry checked runtime provenance. Other
    read(query)->tagged-primitive providers are useful for deterministic tests
    and are always labeled unverified; their dictionaries cannot claim live
    Windows provenance. A supplied observer's close() is called once after the
    evaluation, including errors. Instances retain the latest partial report.
    """
    def __init__(self, observer):
        self.observer = observer
        self.last_report = None
        self._used = False

    def evaluate(self, condition_json: bytes, *, file_context: bytes) -> LiveConditionReport:
        if self._used:
            raise ValueError('Live evaluation requires a fresh observer and wrapper')
        if type(self.observer) is WindowsConditionRegistry and (
                self.observer._records or self.observer._closed or self.observer._failure is not None
                or self.observer._terminal):
            # Reject an already used session before another query is issued.
            # Receipt-sequence validation alone would discover reuse only
            # after consuming a fresh registry observation from that session.
            raise ValueError('Live evaluation requires a fresh Windows registry observer')
        self.last_report = None
        self._used = True
        document = {'profile': PROFILE, 'scope': 'Lazy registry condition observations with supplied file facts',
            'file_context_source': 'caller_supplied', 'file_context_verified': False,
            'registry_provider_profile': leaves.PROVIDER, 'registry_provider_identity_verified': False,
            'atomic_machine_snapshot': False, 'package_applicability_evaluated': False,
            'metadata_admission_evaluated': False, 'publisher_trust_evaluated': False, 'updates_available': None,
            'condition_result': None, 'evaluation_completed': False, 'observer_closed': False,
            'events': [], 'condition_result_cache': {}, 'registry_observations': [],
            'grammar_provenance': 'Accepted bounded Boolean parser; recursive parenthesized NOT is source-composed',
            'stages': [{'stage': stage, 'status': 'not_run'} for stage in core.STAGES]}
        rows = {row['stage']: row for row in document['stages']}
        current = core.STAGES[0]; first = None; expected_outcome = None

        def emergency(cause):
            # No JSON encoder, mutable provider value or exception renderer here.
            result = document['condition_result']
            text = ('{"profile":"' + PROFILE + '","evidence_export_failed":true,'
                '"original_error_retained":true,"publisher_trust_evaluated":false,'
                '"package_applicability_evaluated":false,"updates_available":null,"condition_result":'
                + ('true' if result is True else 'false' if result is False else 'null'))
            for key in ('conditions_sha256', 'file_context_sha256'):
                if key in document:
                    text += ',"' + key + '":"' + document[key] + '"'
            self.last_report = LiveConditionReport(text + '}', cause, result)
            return self.last_report

        def finish(cause):
            try:
                # The shared leaf uses the supplied-fact label internally. This
                # detached report has an explicit sequence/provider association.
                for event in document['events']:
                    sequence = event.get('registry_observation_sequence')
                    if sequence is not None:
                        for observation in event['observations']:
                            if observation.get('provider') == leaves.PROVIDER:
                                observation['source'] = 'registry_observation_sequence'
                                observation['sequence'] = sequence
                                if observation['status'] == 'supplied':
                                    observation['status'] = 'observed'
                observations = document['registry_observations']
                document['registry_provider_identity_verified'] = bool(observations) and all(
                    row['provider_identity_verified'] for row in observations)
                self.last_report = LiveConditionReport(json.dumps(document, ensure_ascii=True, allow_nan=False),
                    cause, document['condition_result'])
                return self.last_report
            except BaseException as error:
                report = emergency(cause if cause is not None else error)
                if cause is None:
                    raise
                return report

        try:
            for name, raw in (('conditions', condition_json), ('file_context', file_context)):
                if type(raw) is bytes and 0 < len(raw) <= core.MAX_JSON_BYTES:
                    document[name + '_sha256'] = hashlib.sha256(raw).hexdigest()
            try:
                data = core._json(condition_json, limit=core.MAX_JSON_BYTES, depth_limit=12); core._ascii(data)
                document['raw_typed_data'] = data
                model = core._typed(data); document['typed_model'] = model
                rows[current].update(status='passed')
                current = 'context_input'
                context_data = core._json(file_context, limit=core.MAX_JSON_BYTES, depth_limit=12); core._ascii(context_data)
                facts = core._facts(context_data)
                document['supplied_file_context'] = context_data
                rows[current].update(status='passed', culture='invariant-ascii', file_records=len(facts))
            except core._Outcome:
                raise
            except ValueError as error:
                raise core._Outcome('failed', str(error)) from error
            current = 'definition_validation'
            definitions = core._validate(model)
            rows[current].update(status='passed')
            document['normalized_expression'] = model['expression'].lower()
            document['normalized_names'] = [{'name': row['name'], 'lookup_name': row['name'].lower()} for row in model['conditions']]
            current = 'expression_domain'
            ast = core._Parser(model['expression']).parse(); rows[current].update(status='passed')
            current = 'expression_evaluation'
            result = core._evaluate(ast, definitions, facts, document, _LiveFacts(self.observer, document))
            document.update(condition_result=result, evaluation_completed=True)
            rows[current].update(status='passed', result=result)
            visited = {row['lookup_name'] for row in document['events']}
            document['unrequested_definition_names'] = [row['name'] for row in model['conditions'] if row['name'].lower() not in visited]
        except core._Outcome as error:
            expected_outcome = error
            rows[current].update(error.details)
        except BaseException as error:
            first = error
            try:
                rows[current].update(status='failed', interrupted=True)
                document['interrupted'] = _error(error)
            except BaseException:
                pass
        # No evidence construction is allowed to replace the first operation or
        # cleanup exception. Closing never requests a registry value.
        try:
            self.observer.close()
            document['observer_closed'] = True
        except BaseException as error:
            if first is None:
                # Expected provider/domain errors already live in their stage;
                # Windows close re-raises that same first _Outcome, not a new KI.
                if error is expected_outcome:
                    document['observer_close_outcome'] = dict(error.details)
                else:
                    first = error
            try: document['observer_close_error'] = _error(error)
            except BaseException: document['observer_close_error_export_failed'] = True
        if type(self.observer) is WindowsConditionRegistry:
            try:
                evidence = self.observer.last_report
                if evidence is not None:
                    document['observer_evidence'] = evidence.as_dict()
            except BaseException as error:
                if first is None: first = error
        report = finish(first)
        if first is not None:
            try: first.toolkit_live_update_conditions_evidence = report.as_dict()
            except BaseException: pass
            raise first
        return report
