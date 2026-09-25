"""One-shot Trigger Control invocation of a retained KEYGL5 scene binding."""
from __future__ import annotations

from dataclasses import dataclass

from .cgate import CGateError
from .edlt import EdltError, _apply_error_text
from .edlt_scene_live import _network, _reply
from .edlt_scene_manager import EdltSceneManager, SceneManagerState


def _error(error):
    return type(error).__name__, _apply_error_text(error)[:2048]


@dataclass(frozen=True)
class SceneTriggerPlan:
    network: str
    scene: int
    trigger_group: int
    action_selector: int
    force: bool

    @property
    def address(self):
        return f'{self.network}/202/{self.trigger_group}'

    @property
    def command(self):
        return (f'TRIGGER EVENT {self.address} {self.action_selector}'
                + (' FORCE' if self.force else ''))

    def as_dict(self):
        return {
            'format': 'cbus-edlt-scene-trigger-plan-v1',
            'profile': {'unit_type': 'KEYGL5',
                        'catalog_number': '5055EDL',
                        'firmware': '5.5.00'},
            'network': self.network,
            'scene': self.scene,
            'trigger_application': 202,
            'trigger_group': self.trigger_group,
            'action_selector': self.action_selector,
            'force': self.force,
            'address': self.address,
            'command': self.command,
            'binding_source': 'retained KEYGL5 scene table',
            'metadata_created': False,
            'source_snapshot_freshness_verified': False,
            'metadata_cache_freshness_verified': False,
            'physical_binding_readback': False,
            'source_profile_identity_verified': True,
            'network_io_performed': False,
            'saved': False,
            'pp_writes': 0,
        }


@dataclass(frozen=True)
class SceneTriggerOutcome:
    plan: SceneTriggerPlan
    status: str
    submitted: bool
    reply_code: int | None = None
    reply_lines: tuple[str, ...] = ()
    error_type: str | None = None
    error: str | None = None
    outcome_uncertain: bool = False

    @property
    def complete(self):
        return self.status == 'accepted'

    def as_dict(self):
        return {
            'operation': 'trigger-retained-scene',
            **self.plan.as_dict(),
            'format': 'cbus-edlt-scene-trigger-v1',
            'status': self.status,
            'complete': self.complete,
            'operation_completed': self.complete,
            'submitted': self.submitted,
            'attempted_count': int(self.submitted),
            'reply_code': self.reply_code,
            'reply_lines': list(self.reply_lines),
            'error': (None if self.error_type is None else
                      {'type': self.error_type, 'message': self.error}),
            'native_command_accepted': self.complete,
            'protocol_rejection_confirmed': self.status == 'native-rejected',
            'outcome_uncertain': self.outcome_uncertain,
            'network_io_performed': self.submitted,
            'device_side_effect_possible': self.submitted,
            'target_scope': 'all C-Bus listeners for the trigger group and action selector',
            'physical_scene_execution_verified': False,
            'device_verified': False,
            'saved': False,
            'pp_writes': 0,
            'automatic_retries': 0,
            'rollback_performed': False,
        }


class NativeEdltSceneTrigger:
    """Resolve and submit one retained scene Trigger event without retry."""

    def __init__(self, manager, client, *, network):
        if type(manager) is not EdltSceneManager:
            raise EdltError('Use an EdltSceneManager instance')
        if not callable(getattr(client, 'command', None)):
            raise EdltError('A C-Gate command client is required')
        self.manager = manager
        self.client = client
        self.network = _network(network)
        self.last_outcome = None
        self.last_evidence = None
        self.last_error = None

    def _start(self):
        self.last_outcome = None
        self.last_evidence = None
        self.last_error = None

    def plan(self, state, *, scene=1, force=False):
        self._start()
        if type(state) is not SceneManagerState:
            raise EdltError('Use an intact scene object issued by this EdltSceneManager instance; exports are review-only')
        if type(force) is not bool:
            raise EdltError('Force must be boolean')
        trigger, action = self.manager.live_trigger(state, scene=scene)
        return SceneTriggerPlan(self.network, scene, trigger, action, force)

    def _remember(self, outcome, error=None):
        self.last_outcome = outcome
        self.last_evidence = outcome.as_dict()
        self.last_error = error
        if error is not None:
            try:
                error.edlt_scene_live_evidence = self.last_evidence
            except BaseException:
                pass
        return outcome

    def trigger(self, state, *, scene=1, force=False):
        plan = self.plan(state, scene=scene, force=force)
        if self.client.connected is not True:
            error = RuntimeError(
                'C-Gate is not connected; connect explicitly before triggering a scene')
            kind, text = _error(error)
            return self._remember(SceneTriggerOutcome(
                plan, 'not-connected', False, error_type=kind, error=text), error)

        try:
            try:
                response = self.client.command(plan.command)
            except CGateError as rejected:
                response = rejected.response
        except BaseException as error:
            kind, text = _error(error)
            outcome = self._remember(SceneTriggerOutcome(
                plan, 'transport-error', True, error_type=kind, error=text,
                outcome_uncertain=True), error)
            if not isinstance(error, Exception):
                raise
            return outcome

        try:
            response = _reply(response)
        except BaseException as error:
            kind, text = _error(error)
            outcome = self._remember(SceneTriggerOutcome(
                plan, 'response-error', True, error_type=kind, error=text,
                outcome_uncertain=True), error)
            if not isinstance(error, Exception):
                raise
            return outcome

        if 400 <= response.code < 500 and response.code != 408:
            return self._remember(SceneTriggerOutcome(
                plan, 'native-rejected', True, reply_code=response.code,
                reply_lines=response.lines, error_type='NativeRejected',
                error=response.final))
        if response.code == 408 or 500 <= response.code < 600:
            return self._remember(SceneTriggerOutcome(
                plan, 'native-outcome-uncertain', True,
                reply_code=response.code, reply_lines=response.lines,
                error_type='NativeOutcomeUncertain', error=response.final,
                outcome_uncertain=True))
        if response.code != 200 or len(response.lines) != 1:
            error = EdltError('Scene trigger requires a single terminal200 reply')
            kind, text = _error(error)
            return self._remember(SceneTriggerOutcome(
                plan, 'response-error', True, reply_code=response.code,
                reply_lines=response.lines, error_type=kind, error=text,
                outcome_uncertain=True), error)
        return self._remember(SceneTriggerOutcome(
            plan, 'accepted', True, reply_code=response.code,
            reply_lines=response.lines))
