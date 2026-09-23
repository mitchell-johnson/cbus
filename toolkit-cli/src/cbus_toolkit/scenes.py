"""C-Gate filesystem scenes: bounded editing and native PLAY/RECORD commands.

These are the server's scene-base files, not SQLite Scene entities or device
PP scene tables. Native loading requires use-scenes=yes and a scene-set
directory present when its scene manager starts.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import re
import tempfile

from .cgate import CGateResponse
from .native import _token

MAX_FILE_BYTES = 1024 * 1024
MAX_ACTIONS = 1024


class SceneError(ValueError):
    pass


def _address(value):
    if not isinstance(value, str):
        raise SceneError("Scene addresses must be strings")
    value = _token(value, 'scene address')
    if '#' in value:
        raise SceneError("Scene addresses cannot contain the native # comment marker")
    return value


@dataclass(frozen=True)
class SceneAction:
    address: str
    level: int
    ramp_seconds: int = 0

    def __post_init__(self):
        _address(self.address)
        if isinstance(self.level, bool) or not isinstance(self.level, int) or not 0 <= self.level <= 255:
            raise SceneError("Scene level must be an integer in 0..255")
        if isinstance(self.ramp_seconds, bool) or not isinstance(self.ramp_seconds, int) or not 0 <= self.ramp_seconds <= 2147483647:
            raise SceneError("Scene ramp seconds must be a nonnegative signed 32-bit integer")


@dataclass(frozen=True)
class SceneFile:
    actions: tuple[SceneAction, ...] = ()
    play_trigger: str | None = None
    record_trigger: str | None = None
    comments: tuple[str, ...] = ()
    _original_text: str | None = field(default=None, repr=False, compare=False)
    _original_values: tuple | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        actions = tuple(self.actions)
        if len(actions) > MAX_ACTIONS or any(not isinstance(action, SceneAction) for action in actions):
            raise SceneError(f"Scene must contain at most {MAX_ACTIONS} typed actions")
        object.__setattr__(self, 'actions', actions)
        for address in (self.play_trigger, self.record_trigger):
            if address is not None:
                _address(address)
        comments = tuple(self.comments)
        if any(not isinstance(comment, str) or '\n' in comment or '\r' in comment or not comment.lstrip().startswith('#') for comment in comments):
            raise SceneError("Scene comments must be individual # comment lines")
        object.__setattr__(self, 'comments', comments)

    def _values(self):
        return (self.actions, self.play_trigger, self.record_trigger, self.comments)

    @classmethod
    def parse(cls, text):
        if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_FILE_BYTES:
            raise SceneError("Scene text exceeds the 1 MiB input limit")
        actions, comments = [], []
        triggers = {'play': None, 'record': None}
        for number, line in enumerate(text.splitlines(), 1):
            command, marker, comment = line.partition('#')
            if marker:
                comments.append('#' + comment)
            tokens = command.split()
            if not tokens:
                continue
            verb = tokens[0].lower()
            try:
                if verb in triggers and len(tokens) == 2:
                    triggers[verb] = _address(tokens[1])
                elif verb == 'set' and len(tokens) in (3, 4):
                    if any(re.fullmatch(r'[+-]?[0-9]+', value) is None for value in tokens[2:]):
                        raise SceneError("Scene levels and times use decimal integers")
                    level = int(tokens[2], 10)
                    seconds = int(tokens[3], 10) if len(tokens) == 4 else 0
                    actions.append(SceneAction(tokens[1], level, seconds))
                else:
                    raise SceneError("Use play address, record address, or set address decimal-level [decimal-seconds]")
            except ValueError as error:
                raise SceneError(f"Scene line {number}: {error}") from error
        result = cls(tuple(actions), triggers['play'], triggers['record'], tuple(comments))
        return replace(result, _original_text=text, _original_values=result._values())

    @classmethod
    def load(cls, path, *, encoding='utf-8'):
        path = Path(path)
        with path.open('rb') as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise SceneError("Scene file exceeds the 1 MiB input limit")
        try:
            return cls.parse(data.decode(encoding))
        except (UnicodeError, LookupError) as error:
            raise SceneError(f"Scene file is not valid {encoding}") from error

    def to_text(self):
        if self._original_text is not None and self._values() == self._original_values:
            return self._original_text
        lines = list(self.comments)
        if self.play_trigger is not None:
            lines.append('play ' + self.play_trigger)
        if self.record_trigger is not None:
            lines.append('record ' + self.record_trigger)
        lines.extend(f'set {action.address} {action.level} {action.ramp_seconds}' for action in self.actions)
        return '\n'.join(lines) + ('\n' if lines else '')

    def as_dict(self):
        return {'format': 'cbus-native-scene-file-v1', 'play_trigger': self.play_trigger,
                'record_trigger': self.record_trigger, 'comments': list(self.comments),
                'actions': [{'address': action.address, 'level': action.level, 'ramp_seconds': action.ramp_seconds} for action in self.actions]}

    def with_action(self, index, action):
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= len(self.actions):
            raise SceneError("Action index must select an action or append at the end")
        if not isinstance(action, SceneAction):
            raise SceneError("Use a typed SceneAction")
        actions = list(self.actions)
        if index == len(actions):
            actions.append(action)
        else:
            actions[index] = action
        return replace(self, actions=tuple(actions))

    def without_action(self, index):
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(self.actions):
            raise SceneError("Action index must select an existing action")
        return replace(self, actions=self.actions[:index] + self.actions[index + 1:])

    def save(self, path, *, overwrite=False, encoding='utf-8'):
        path = Path(path)
        if path.exists() and not overwrite:
            raise SceneError("Scene output already exists; select overwrite explicitly")
        try:
            data = self.to_text().encode(encoding)
        except (UnicodeError, LookupError) as error:
            raise SceneError(f"Scene cannot be encoded as {encoding}") from error
        if len(data) > MAX_FILE_BYTES:
            raise SceneError("Scene output exceeds the 1 MiB limit")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if overwrite:
                os.replace(temporary, path)
            else:
                # Exclusive publication remains safe if another writer creates
                # the target between the initial existence check and this call.
                os.link(temporary, path)
                temporary.unlink()
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path


class NativeScenes:
    """Queue commands for an existing server scene-set and scene file."""
    def __init__(self, client):
        self.client = client

    def play(self, scene_set, scene):
        return self.client.command(f'SCENE PLAY {_token(scene_set, "scene set")} {_token(scene, "scene name")}')

    def record(self, scene_set, scene):
        return self.client.command(f'SCENE RECORD {_token(scene_set, "scene set")} {_token(scene, "scene name")}')


class SceneExecutionError(RuntimeError):
    """Playback stopped; completed commands must not be replayed implicitly."""
    def __init__(self, index, completed, cause):
        self.index = index
        self.completed = tuple(completed)
        self.cause = cause
        self.details = {"failed_action_index": index, "completed_count": len(completed),
                        "completed_responses": self.completed}
        super().__init__(f'Scene action {index} failed after {len(completed)} accepted commands: {cause}')


@dataclass(frozen=True)
class ScenePlayback:
    responses: tuple[CGateResponse, ...]
    queued: bool = True
    device_verified: bool = False


class SceneExecutor:
    """Explicit Python execution of vendor-format scene files.

    PLAY queues lighting commands in file order without waiting for ramps.
    RECORD samples C-Gate's cached levels, like the native scene recorder;
    it does not establish that physical devices hold those levels. Trigger
    bindings remain file metadata and are not activated by this executor.
    """
    def __init__(self, client):
        self.client = client

    def play(self, scene):
        if not isinstance(scene, SceneFile):
            raise SceneError('Use a typed SceneFile')
        completed = []
        for index, action in enumerate(scene.actions):
            if action.ramp_seconds == 0 and action.level in (0, 255):
                command = f'LIGHTING {"ON" if action.level else "OFF"} {action.address}'
            else:
                command = f'LIGHTING RAMP {action.address} {action.level} {action.ramp_seconds}'
            try:
                response = self.client.command(command)
                if response.code != 200:
                    raise RuntimeError('Lighting command was not accepted: ' + response.final)
            except (RuntimeError, OSError) as error:
                raise SceneExecutionError(index, completed, error) from error
            completed.append(response)
        return ScenePlayback(tuple(completed))

    def record(self, scene):
        if not isinstance(scene, SceneFile):
            raise SceneError('Use a typed SceneFile')
        recorded = []
        for action in scene.actions:
            response = self.client.command(f'GET {action.address} level')
            values = []
            for line in response.lines:
                match = re.fullmatch(r'300[- ](.+): level=([0-9]+)', line)
                if match is not None:
                    values.append(int(match[2]))
            if len(values) != 1 or not 0 <= values[0] <= 255:
                raise SceneError(f'Expected exactly one cached byte level for {action.address}')
            recorded.append(SceneAction(action.address, values[0], 0))
        return replace(scene, actions=tuple(recorded))
