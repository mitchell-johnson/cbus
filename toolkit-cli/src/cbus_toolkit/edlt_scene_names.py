"""Retained SceneName properties for the admitted .NET Framework profile.

Names belong to an issued SceneManager model, rather than its encoded PP rows.
The property allocator keeps the old scene reference until allocation finishes.
The older additive ``set-name-text`` operation has its own unchanged policy.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType

from .edlt import EdltError
from .edlt_static_grid import loaded_name, row_bytes, stored_row


_NET4_STABLE_WHITESPACE = frozenset((
    *range(0x9, 0xE), 0x20, 0x85, 0xA0, 0x1680,
    *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
))

# Literal FixedStrings::.cctor membership. Its culture-sensitive SortedSet
# order and duplicate survivors are deliberately not inferred here.
FIXED_SUGGESTION_NAMES = (
    'Light', 'Lamp', 'Fan', 'Heater', 'A/C', 'Blind', 'Fountain', 'Volume',
    'Treble', 'Bass', 'Balance', 'Source', 'Off', 'Low', 'Medium', 'High',
    'Heat', 'Cool', 'Temperature', 'Away', 'Arm', 'All Off', 'Goodnight',
    'Goodbye', 'Bedroom', 'Bathroom', 'Kitchen', 'Lounge', 'Dining', 'Living',
    'Office', 'Study', 'Ensuite', 'Carport', 'Outside', 'Patio', 'Pool',
    'Rumpus', 'Toilet', 'Pantry', 'Guest', 'Hall', 'Stairs', 'Theatre', 'Shed',
    'BBQ', 'Bar', 'Porch', 'WC', 'WIR', 'Entry', 'Driveway', 'Family', 'Garage',
    'Meeting', 'Lobby', 'Balcony', 'Studio', 'Sauna', 'Gate', 'Outdoor',
    'Sitting', 'Cellar', 'Release the Hounds',
)


def checked_names(names):
    if (type(names) is not tuple or len(names) != 64
            or any(type(name) is not str for name in names)):
        raise EdltError('SceneName requires all 64 retained names')
    return names


def load_names(values):
    return tuple(loaded_name(row_bytes(values, index)) for index in range(64))


def scene_name(names, index):
    """EDLTScene.SceneName returns empty for an out-of-table NameIndex."""
    checked_names(names)
    if type(index) is not int:
        raise EdltError('SceneName index must be an integer')
    return names[index] if 0 <= index < 64 else ''


def scene_names_view(names, indices):
    """Eight source ScenesNameValue rows, without guessing the index64 bug."""
    checked_names(names)
    if (type(indices) is not tuple or len(indices) != 8
            or any(type(index) is not int or index not in (*range(64), 255)
                   for index in indices)):
        raise EdltError('SceneName view requires eight indices in 0..63 or255')
    return tuple({'value': slot - 1, 'name': str(slot) + ' - ' + scene_name(names, index),
                  'scene': slot, 'name_index': index, 'scene_name': scene_name(names, index)}
                 for slot, index in enumerate(indices, 1))


def _blank(text):
    # .NET4 host Unicode tables disagree on180E. A proved nonwhite character
    # determines nonblank independently of that version-dependent character.
    codes = tuple(map(ord, text))
    if any(code not in _NET4_STABLE_WHITESPACE and code != 0x180E for code in codes):
        return False
    if 0x180E in codes:
        raise EdltError('SceneName blankness containing only whitespace and U+180E requires the original Framework Unicode table')
    return True


def save_names(values, names):
    """SaveStaticText compares decoded PP with every retained Name first."""
    checked_names(names)
    changes, setters = {}, []
    for index, name in enumerate(names):
        previous = row_bytes(values, index)
        if loaded_name(previous) == name:
            continue
        try:
            data = stored_row(name)
        except UnicodeEncodeError as error:
            raise EdltError('SceneName storage requires valid Unicode') from error
        setters.append(index)
        if data != previous:
            changes[f'StaticTextString{index}'] = tuple(data)
    return changes, tuple(setters)


@dataclass(frozen=True)
class SceneNameAssignment:
    index: int
    names: tuple[str, ...]
    text: str | None
    reused: bool
    ignored_null: bool
    changes: object
    used_indices: tuple[int, ...]
    setter_indices: tuple[int, ...]

    def __post_init__(self):
        checked_names(self.names)
        object.__setattr__(self, 'changes', MappingProxyType(dict(self.changes)))

    def as_dict(self):
        return {'index': self.index, 'text': self.text, 'reused': self.reused,
                'ignored_null': self.ignored_null, 'used_indices': list(self.used_indices),
                'setter_indices': list(self.setter_indices),
                'allocation_policy': 'SceneName property; old reference retained until assignment',
                'whitespace_profile': 'net4-stable-whitespace',
                'changes': {name: list(value) for name, value in self.changes.items()}}


def assign_name(names, old_index, text, *, values, used_indices):
    """Source property assignment; ``used_indices`` includes the old reference.

    Unlike the historical additive API, nonblank property text has no63-byte
    gate. Its retained full Name and the truncated UTF-8 PP are distinct facts.
    """
    checked_names(names)
    if text is None:
        return SceneNameAssignment(old_index, names, None, False, True, {}, (), ())
    if type(text) is not str:
        raise EdltError('SceneName property must be a string or null')
    try:
        text.encode('utf-8')
    except UnicodeEncodeError as error:
        raise EdltError('SceneName property requires valid Unicode') from error
    if _blank(text):
        return SceneNameAssignment(255, names, text, False, False, {}, (), ())
    match = next((index for index, name in enumerate(names) if name == text), None)
    if match is not None:
        return SceneNameAssignment(match, names, text, True, False, {}, (), ())
    used = tuple(sorted(set(used_indices())))
    if len(used) > 63:
        raise EdltError("Static text table is full under Toolkit's used-reference capacity check")
    index = next((candidate for candidate in range(63, -1, -1) if candidate not in used), None)
    if index is None:
        raise EdltError('Static text table has no unreferenced slot')
    updated = list(names); updated[index] = text; updated = tuple(updated)
    changes, setters = save_names(values, updated)
    return SceneNameAssignment(index, updated, text, False, False, changes, used, setters)


@contextmanager
def isolated_additive_cache(values, names, *, retained):
    """Keep the existing additive allocator without touching a parent branch.

    Standalone additive calls still scan strict UTF-8 PP and enforce63 bytes.
    Parent-derived calls use an isolated copy of their issued retained table.
    """
    from . import edlt_static_grid as grid
    if retained:
        with grid.scope():
            grid.initialize(values)
            local = grid.current(values)
            local.names[:] = checked_names(names)
            yield local
    else:
        token = grid._current.set(None)
        try:
            yield None
        finally:
            grid._current.reset(token)
