"""Native timeline consumes old and current Language epochs without I/O."""
from dataclasses import replace
import json

import pytest

from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_metadata import resolve_native_scene_metadata
from cbus_toolkit.edlt_scene_inventory_timeline import check_timeline
from tests.test_edlt_scene_language_initializer import language_source,bridge,LITERALS,UNIT,operation


def resolve(data,capability,projected,operations):
    return resolve_native_scene_metadata(projected,UNIT,data[4],data[1],operations,
        _initialization_timeline=capability)


@pytest.mark.parametrize('setter',[False,True],ids=['valid-getter-old','explicit-setter-current'])
def test_actual_getter_or_setter_chooses_its_exact_language_epoch(setter):
    data=language_source();capability,projected,_m=bridge(data)
    operations=([{'op':'set-action','scene':1,'action':7}] if setter else [])
    operations += [{'op':'get-selector-view','scene':1}]
    metadata=resolve(data,capability,projected,operations)
    engine=data[1]; state=engine.load(data[4],metadata=metadata.cache)
    assert state.scenes[0].dynamic_labels is capability.initial_scene_labels(1)
    outcome=engine.edit(state,operations=metadata.operations)
    names=[row.name for row in outcome.state.scenes[0].dynamic_labels]
    assert names==LITERALS['current_labels' if setter else 'old_labels']
    if not setter:assert outcome.state.scenes[0].dynamic_labels is state.scenes[0].dynamic_labels
    timeline=metadata.cache._inventory_timeline
    assert timeline._initial.refresh_generation==data[5]._initial.refresh_generation+1
    assert metadata.as_dict()['inventory_timeline']['binding']['language_initializer_sha256']==capability.fingerprint
    assert data[2].commands==[]


def test_explicit_trigger_current_refresh_adopts_current_language():
    data=language_source();capability,projected,_m=bridge(data)
    rows=[{'op':'scene-selector-control','scene':1,'events':[
        {'event':'scene-current-changed','current':True},{'event':'trigger-current-changed'}]}]
    metadata=resolve(data,capability,projected,rows)
    outcome=data[1].edit(data[1].load(data[4],metadata=metadata.cache),operations=metadata.operations)
    assert [row.name for row in outcome.state.scenes[0].dynamic_labels]==LITERALS['current_labels']


def test_old_language_label_owner_survives_validation_and_terminal_branches():
    data=language_source();capability,projected,_m=bridge(data)
    metadata=resolve(data,capability,projected,[{'op':'get-selector-view','scene':1}])
    engine=data[1];outcome=engine.edit(engine.load(data[4],metadata=metadata.cache),operations=metadata.operations)
    old=outcome.state.scenes[0].dynamic_labels
    validated=engine.validate(outcome.state)
    plan=engine.prepare_composition(outcome.state)
    assert validated.state.scenes[0].dynamic_labels is old
    assert plan.terminal.scenes[0].dynamic_labels is old
    assert [row.name for row in old]==LITERALS['old_labels']


def test_rebase_keeps_language_epochs_and_old_object_identity():
    data=language_source();capability,projected,_m=bridge(data)
    metadata=resolve(data,capability,projected,[{'op':'get-selector-view','scene':1}])
    timeline=metadata.cache._inventory_timeline
    rebased=timeline.rebase_outer(metadata.cache)
    check_timeline(rebased,owner=data[1]._owner)
    for slot in range(1,9):
        assert rebased.start(rebased._template,source_values=data[4],owner=data[1]._owner).initial_scene_labels(slot) is capability.initial_scene_labels(slot)
    assert rebased._label_epochs==timeline._label_epochs


def test_plain_initializer_still_requires_exact_original_xml():
    data=language_source();_cap,projected,_m=bridge(data)
    with pytest.raises(EdltError,match='another XML'):
        resolve(data,data[5],projected,[{'op':'get-selector-view','scene':1}])


def test_language_bridge_does_not_authorize_changed_scene_owner():
    data=language_source();capability,projected,_m=bridge(data)
    values=dict(data[4]);bucket=list(values['SceneBucket'])
    bucket[values['Scene1StartAddress'][0]+3]=1;values['SceneBucket']=tuple(bucket)
    with pytest.raises(EdltError,match='trigger/action owners'):
        resolve_native_scene_metadata(projected,UNIT,data[4],data[1],
            [{'op':'get-selector-view','scene':1}],_projected_values=values,
            _initialization_timeline=capability)


def test_noop_preserves_old_objects_and_does_not_increment_generation():
    data=language_source();capability,projected,_m=bridge(data,[operation((1,2))])
    metadata=resolve(data,capability,projected,[{'op':'get-selector-view','scene':1}])
    state=data[1].load(data[4],metadata=metadata.cache)
    assert state.scenes[0].dynamic_labels is capability.initial_scene_labels(1)
    assert metadata.cache._inventory_timeline._initial.refresh_generation==data[5]._initial.refresh_generation


def test_raw_bridge_receipt_never_enters_native_initializer():
    data=language_source();capability,projected,_m=bridge(data)
    with pytest.raises(EdltError,match='foreign'):
        resolve(data,capability.as_dict(),projected,[{'op':'get-selector-view','scene':1}])


@pytest.mark.parametrize('language',[False,True],ids=['plain-original','changed-language'])
def test_newly_consumed_existing_level_uses_its_observed_original_label_epoch(language):
    data=language_source()
    if language:
        capability,projected,_m=bridge(data)
    else:
        capability,projected=data[5],data[3]
    operations=[{'op':'set-trigger','scene':1,'group':43},
                {'op':'set-action','scene':1,'action':7},
                {'op':'get-selector-view','scene':1}]
    metadata=resolve(data,capability,projected,operations)
    engine=data[1];state=engine.load(data[4],metadata=metadata.cache)
    outcome=engine.edit(state,operations=metadata.operations)
    assert state.scenes[0].dynamic_labels is data[5].start(data[5]._template,
        source_values=data[4],owner=engine._owner).initial_scene_labels(1)
    assert [row.name for row in outcome.state.scenes[0].dynamic_labels]==LITERALS['current_labels' if language else 'old_labels']
    old_epoch=metadata.cache._inventory_timeline.label_template_at(0)
    observed=next(row for row in old_epoch if (row.group,row.action)==(43,7))
    assert [row.name for row in observed.labels]==LITERALS['old_labels']
    assert metadata.creations==()
    assert data[2].commands==[]
