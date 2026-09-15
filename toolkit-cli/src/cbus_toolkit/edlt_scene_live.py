"""One-shot capture/broadcast over retained eDLT scene references.

Commands are serial and wait for terminal C-Gate replies. This does not model
WinForms asynchronous timing, its timer, or physical receiver acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

from .cgate import CGateError, CGateResponse
from .edlt import EdltError, _apply_error_text, _int
from .edlt_scene_manager import EdltSceneManager, SceneCaptureLevel, SceneManagerState


def _network(value):
    if not isinstance(value, str):
        raise EdltError('Use an explicit live network such as //PROJECT/254')
    match = re.fullmatch(r'//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})', value)
    if match is None or int(match[2]) > 255:
        raise EdltError('Use an explicit live network such as //PROJECT/254')
    return value


def _error(error):
    return type(error).__name__, _apply_error_text(error)[:2048]


def _reply(value):
    if (type(value) is not CGateResponse or type(value.code) is not int
            or not 100 <= value.code <= 999 or not isinstance(value.lines, tuple)
            or not 1 <= len(value.lines) <= 16
            or any(not isinstance(line, str) or len(line) > 2048 or
                   any(ord(c) < 32 or ord(c) == 127 for c in line) for line in value.lines)
            or value.final != value.lines[-1]
            or not value.final.startswith(str(value.code) + ' ')):
        raise EdltError('Malformed or unsupported C-Gate scene reply')
    return value


def _level(text):
    # Int32.TryParse(Integer) followed by the original item Level byte clamp.
    # Values outside the byte range are retained as normalization evidence,
    # never presented as verified C-Bus levels.
    if not re.fullmatch(r' *[+-]?[0-9]+ *', text):
        return 0, None, False, 'legacy-zero'
    value = int(text)
    if not -(2**31) <= value < 2**31:
        return 0, None, False, 'legacy-zero'
    return max(0, min(255, value)), value, 0 <= value <= 255, 'verified' if 0 <= value <= 255 else 'normalized'


@dataclass(frozen=True)
class SceneLiveItemResult:
    item: int
    item_id: int
    application: int
    group: int
    address: str
    command: str
    previous_level: int
    requested_level: int | None
    status: str = 'attempted'
    level: int | None = None
    native_level: int | None = None
    reply_code: int | None = None
    reply_lines: tuple[str, ...] = ()
    error_type: str | None = None
    error: str | None = None
    outcome_uncertain: bool = False

    def as_dict(self):
        return {**self.__dict__, 'reply_lines': list(self.reply_lines),
                'verified_observation': self.status == 'verified',
                'native_command_accepted': self.status == 'accepted',
                'legacy_zero_fallback': self.status == 'legacy-zero'}


@dataclass(frozen=True)
class SceneLiveOutcome:
    operation: str
    network: str
    scene: int
    scope: str
    selected_item: int | None
    source: SceneManagerState
    state: SceneManagerState | None
    items: tuple[SceneLiveItemResult, ...]
    complete: bool
    sequence_finished: bool
    requested_count: int
    error_type: str | None = None
    error: str | None = None

    def as_dict(self):
        return dict(format='cbus-edlt-scene-live-v1', operation=self.operation,
            network=self.network, scene=self.scene, scope=self.scope, selected_item=self.selected_item,
            complete=self.complete, operation_completed=self.complete, sequence_finished=self.sequence_finished,
            original_handler_completed=self.sequence_finished if self.operation == 'capture' else None,
            requested_count=self.requested_count, attempted_count=len(self.items),
            items=[row.as_dict() for row in self.items],
            state=None if self.state is None else self.state.as_dict(),
            model_changed=self.state is not None and self.state.scenes != self.source.scenes,
            error=None if self.error_type is None else {'type': self.error_type, 'message': self.error},
            transport_outcome_uncertain=any(row.outcome_uncertain for row in self.items),
            completion_boundary='serial C-Gate terminal replies',
            capture_reads_verified=self.complete if self.operation == 'capture' else None,
            saved=False, pp_writes=0, automatic_retries=0, rollback_performed=False,
            metadata_created=False, background_tasks_started=0, physical_device_verified=False,
            ui_asynchronous_timing_verified=False, timer_behavior_implemented=False)


class NativeEdltSceneLive:
    def __init__(self, manager, client, *, network):
        if type(manager) is not EdltSceneManager:
            raise EdltError('Use an EdltSceneManager instance')
        if not callable(getattr(client, 'command', None)):
            raise EdltError('A connected C-Gate command client is required')
        self.manager, self.client, self.network = manager, client, _network(network)
        self.last_evidence = None
        self.last_outcome = None
        self.last_error = None

    def _start(self, state, scene):
        self.last_evidence = self.last_outcome = self.last_error = None
        _network(self.network)
        items = self.manager.live_items(state, scene=scene)
        # Validate every target before sending the first command, including
        # hidden retained references from a previous application selection.
        for item in items:
            app = item.group.application
            if type(app) is not int or not (48 <= app <= 127 or app == 136):
                raise EdltError('Live scenes require a supported lighting application')
            _int(item.group.group, 'Retained lighting group', 0, 254)
            _int(item.level, 'Retained level')
        return items

    def _record(self, operation, item, index):
        address = f'{self.network}/{item.group.application}/{item.group.group}'
        command = (f'GET {address} Level' if operation == 'capture' else
                   f'RAMP {address} {item.level} 0 FORCE')
        return SceneLiveItemResult(index, item.item_id, item.group.application, item.group.group,
                                  address, command, item.level, None if operation == 'capture' else item.level)

    def _remember(self, outcome, error=None):
        self.last_outcome = outcome
        self.last_error = error
        export_failure = None
        try:
            evidence = outcome.as_dict()
        except BaseException as secondary:
            kind, text = _error(secondary)
            evidence = dict(operation=outcome.operation, complete=False, saved=False, pp_writes=0,
                attempted_count=len(outcome.items), attempted_item_ids=[v.item_id for v in outcome.items],
                evidence_export_complete=False, evidence_error={'type': kind, 'message': text},
                automatic_retries=0, rollback_performed=False, physical_device_verified=False)
            if error is None:
                export_failure = secondary
                self.last_error = secondary
        self.last_evidence = evidence
        cause = error if error is not None else export_failure
        if cause is not None:
            try: cause.edlt_scene_live_evidence = evidence
            except BaseException: pass
        if export_failure is not None:
            raise export_failure
        return outcome

    def _capture_result(self, source, scene, rows, readings, finished, requested, error=None):
        failure = _error(error) if error is not None else (None, None)
        state_interruption = None
        try:
            state = self.manager.capture_levels(source, scene=scene, readings=readings, finished=finished)
        except BaseException as secondary:
            # Evidence construction must not replace a first interruption.
            state = None
            if error is None:
                error = secondary
                failure = _error(secondary)
                if not isinstance(secondary, Exception): state_interruption = secondary
            else:
                failure = (failure[0], failure[1] + '; retained state export failed: ' + _error(secondary)[1])
        outcome = SceneLiveOutcome('capture', self.network, scene, 'all', None, source, state,
            tuple(rows), bool(state is not None and state.complete), finished, requested, *failure)
        result = self._remember(outcome, error)
        if state_interruption is not None:
            raise state_interruption
        return result

    def capture(self, state, *, scene=1):
        items = self._start(state, scene)
        # Reserve/check the bounded history and pure transition before I/O.
        self.manager.capture_levels(state, scene=scene, readings=(), finished=False)
        rows, readings = [], []
        for index, item in enumerate(items, 1):
            row = self._record('capture', item, index)
            try:
                if self.client.connected is not True:
                    raise RuntimeError('C-Gate is not connected; connect explicitly before capture')
                rows.append(row)
                try: response = self.client.command(row.command)
                except CGateError as rejected: response = rejected.response
            except BaseException as error:
                if not rows or rows[-1].item_id != row.item_id:
                    # No command was submitted for this item.
                    result = self._capture_result(state, scene, rows, readings, False, len(items), error)
                else:
                    kind, text = _error(error)
                    rows[-1] = replace(row, status='transport-error', error_type=kind, error=text, outcome_uncertain=True)
                    result = self._capture_result(state, scene, rows, readings, False, len(items), error)
                if not isinstance(error, Exception): raise
                return result
            try:
                response = _reply(response)
                row = replace(row, reply_code=response.code, reply_lines=response.lines)
                if 400 <= response.code < 600:
                    row = replace(row, status='legacy-zero', level=0,
                                  error_type='NativeRejected', error='Failed GET uses the original unverified zero fallback')
                else:
                    if response.code != 300 or len(response.lines) != 1:
                        raise EdltError('Only a single native300 Level reply is supported')
                    prefix = f'300 {row.address}: Level='
                    if not response.final.startswith(prefix):
                        raise EdltError('Native capture reply lacks the exact addressed Level field')
                    level, native_level, verified, status = _level(response.final[len(prefix):])
                    row = replace(row, status=status, level=level, native_level=native_level,
                        error_type=None if verified else 'UnverifiedLevel',
                        error=None if verified else 'Original level fallback or normalization is not a verified byte reading')
                rows[-1] = row
                readings.append(SceneCaptureLevel(row.item_id, row.level, row.status == 'verified'))
            except BaseException as error:
                kind, text = _error(error)
                rows[-1] = replace(row, status='response-error', error_type=kind, error=text)
                result = self._capture_result(state, scene, rows, readings, False, len(items), error)
                if not isinstance(error, Exception): raise
                return result
        return self._capture_result(state, scene, rows, readings, True, len(items))

    def validate_broadcast(self, state, *, scene=1, scope='current', item=None):
        """Return ordered immutable requests without connecting or sending."""
        items = self._start(state, scene)
        if scope not in ('current', 'all'):
            raise EdltError('Broadcast scope must be current or all')
        if scope == 'all':
            if item is not None: raise EdltError('An item selection is only valid for current scope')
            selected, targets = None, tuple(enumerate(items, 1))
        else:
            selected = item if item is not None else 1 if items else None
            if selected is not None: _int(selected, 'Current item position', 1, len(items))
            targets = () if selected is None else ((selected, items[selected - 1]),)
        return tuple(self._record('broadcast', target, index) for index, target in targets)

    def broadcast(self, state, *, scene=1, scope='current', item=None):
        targets = self.validate_broadcast(state, scene=scene, scope=scope, item=item)
        selected = targets[0].item if scope == 'current' and targets else None
        rows = []
        def finish(finished, error=None):
            failure = _error(error) if error is not None else (None, None)
            outcome = SceneLiveOutcome('broadcast', self.network, scene, scope, selected, state, state,
                tuple(rows), finished and all(v.status == 'accepted' for v in rows), finished, len(targets), *failure)
            return self._remember(outcome, error)
        for row in targets:
            try:
                if self.client.connected is not True:
                    raise RuntimeError('C-Gate is not connected; connect explicitly before broadcast')
                rows.append(row)
                try: response = self.client.command(row.command)
                except CGateError as rejected: response = rejected.response
            except BaseException as error:
                if rows and rows[-1].item_id == row.item_id:
                    kind, text = _error(error)
                    rows[-1] = replace(row, status='transport-error', error_type=kind, error=text, outcome_uncertain=True)
                result = finish(False, error)
                if not isinstance(error, Exception): raise
                return result
            try:
                response = _reply(response)
                row = replace(row, reply_code=response.code, reply_lines=response.lines)
                if 400 <= response.code < 600:
                    rows[-1] = replace(row, status='rejected', error_type='NativeRejected', error=response.final)
                    continue
                if response.code != 200 or len(response.lines) != 1:
                    raise EdltError('Broadcast requires a single terminal200 reply')
                rows[-1] = replace(row, status='accepted')
            except BaseException as error:
                kind, text = _error(error)
                rows[-1] = replace(row, status='response-error', error_type=kind, error=text)
                result = finish(False, error)
                if not isinstance(error, Exception): raise
                return result
        return finish(True)
