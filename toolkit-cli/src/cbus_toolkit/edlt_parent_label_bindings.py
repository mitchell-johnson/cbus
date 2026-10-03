"""Integration of explicit widget control histories into one owning parent.

The adapter modules own source property and callback rules. These helpers
only derive the current scene list and refresh the parent's final references;
neither helper dispatches an implicit UI event or mutating cycle getter.
"""
from __future__ import annotations

from dataclasses import replace

from .edlt import EdltError

APP_GROUP_FAMILIES = ('enable', 'timer', 'shutter', 'multilevel', 'fan', 'room-courtesy')


def current_scene_rows(editor, values):
    from .edlt_scene_names import load_names, scene_names_view
    from .edlt_static_grid import current
    grid = current(values)
    names = load_names(values) if grid is None else tuple(grid.names)
    scenes = editor.lifecycle._scenes(values)
    view = scene_names_view(names, tuple(row[2][4] for row in scenes))
    return tuple({'identity': 'scene:' + str(row['scene']),
                  'value': row['value'], 'name': row['name']} for row in view)


def refresh_scene_references(editor, plan, record, values):
    """Read the exact resulting active references without normalizing storage.

    Component cycle getters accept raw 8. The existing native parent profile
    continues to require configured scenes 0..7 at its final save boundary.
    An empty cycle is valid; dynamic display dependencies must still refuse
    that empty selection in the owning parent.
    """
    from .edlt_scene import SCENE_MODES
    modes = {tuple(pair): mode for mode, pair in SCENE_MODES.items()}
    mode = modes.get(tuple(record[7:9]))
    if mode is None:
        raise EdltError('Scene controls leave an unsupported active macro')
    if mode != 'cycle':
        if record[6] > 7:
            raise EdltError('Scene controls require a configured final scene 0..7')
        reference = editor.scene_reference(values, record[6] + 1)
        return replace(plan, record=record, mode=mode, reference=reference,
                       cycle_references=())
    references = []
    for value in record[13:22]:
        if value > 8:
            break
        if value == 8:
            raise EdltError('Native parent cannot save an unconfigured cycle scene 8')
        references.append(editor.scene_reference(values, value + 1))
    return replace(plan, record=record, mode=mode, reference=None,
                   cycle_references=tuple(references))
