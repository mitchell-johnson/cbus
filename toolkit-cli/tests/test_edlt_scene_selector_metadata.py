"""Native selector identity admission preserves historical v1 contracts."""

import pytest
from cbus_toolkit.edlt import EdltError, _render
from cbus_toolkit.edlt_scene_metadata import resolve_native_scene_metadata
from cbus_toolkit.edlt_scene_manager import EdltSceneManager
from tests.test_edlt_scene_metadata import SceneMetadataClient
from tests.test_edlt_scene_manager import vectors
from tests.test_edlt_lifecycle import fixture


def model():
    spec = fixture()
    engine = EdltSceneManager(spec)
    client = SceneMetadataClient(spec)
    source = engine.snapshot(client.values)
    source.update({name: value for name, value in vectors()['input'].items()
                   if name in spec.parameters})
    client.values = {name: _render(value)
                     for name, value in engine.snapshot(source).items()}
    # This is a native Value attribute, separate from Address; no reflection
    # precedence or original reconciliation for this conflict is established.
    client.applications[202]['groups'][42]['level_values'] = {7: 8}
    return engine, client, engine.snapshot(client.values)


def test_new_selector_profile_refuses_conflicting_named_action_identity():
    engine, client, values = model()
    with pytest.raises(EdltError, match='matching native action Address and Value'):
        resolve_native_scene_metadata(client.xml(), '//TEST/254/p/20', values, engine,
                                      [{'op': 'get-selector-view', 'scene': 1}])
    assert client.commands == []


def test_historical_v1_profile_retains_independent_native_value_admission():
    engine, client, values = model()
    resolved = resolve_native_scene_metadata(client.xml(), '//TEST/254/p/20', values,
                                            engine, [{'op': 'get-action', 'scene': 1}])
    assert resolved.cache.as_dict()['format'] == 'cbus-edlt-scene-manager-cache-v1'
    assert next(row for app in resolved.snapshot.applications if app.address == 202
                for group in app.groups if group.address == 42
                for row in group.level_records if row.address == 7).value == 8
    assert client.commands == []
