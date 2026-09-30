"""Synthetic source-derived Save validation boundary tests; no native execution."""
from dataclasses import replace
from unittest.mock import patch
import pytest
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_templates import EdltTemplateError
from cbus_toolkit.edlt_lifecycle import LifecycleCache
from cbus_toolkit.edlt_reset import _RawState
from cbus_toolkit.edlt_template_model_stage import EdltTemplateModelStage
from cbus_toolkit.edlt_template_lifecycle_stage import EdltTemplateLifecycleStage
from cbus_toolkit.edlt_template_staging import TemplatePpSnapshot
from cbus_toolkit.edlt_template_save_validation import (
    EdltTemplateSaveValidationStage, SaveValidationContext, ValidationDynamicVariant,
    ValidationGroupName, ValidationLevel, TemplateSaveValidationApplyRefused,
    TemplateSaveValidationStageError,
)
from tests.test_edlt_reset import fixture, metadata
from tests.test_edlt_template_staging import template


def model(*, widget=False, scenes=(), changes=None, cache_mode="complete"):
    spec = fixture(); raw = _RawState(spec.defaults()).raw(); bucket = []
    for slot in range(1, 9): raw[f'Scene{slot}StartAddress'] = '0xFFFF'
    for slot, trigger, action, name in scenes:
        raw[f'Scene{slot}StartAddress'] = hex(len(bucket))
        bucket.extend((2, 0, trigger, action, name))
    raw['SceneBucket'] = ' '.join(hex(n) for n in bucket + [255] * (232-len(bucket)))
    if widget:
        raw.update(Widget6WidgetType='0x6', Widget6WidgetByteValue1='0x16',
                   Widget6WidgetByteValue11='0x0', Widget6WidgetByteValue12='0x0')
        for byte in range(13, 22): raw[f'Widget6WidgetByteValue{byte}'] = '0xFF'
        raw['Widget6WidgetByteValue13'] = '0x0'
    raw.update(changes or {})
    cache = LifecycleCache.from_dict(metadata(cache_mode)['lifecycle']); issuer = EdltTemplateModelStage(spec)
    return raw, cache, issuer, issuer.stage(raw, metadata=cache)


def stage(parts, context=None):
    raw, cache, issuer, upstream = parts
    validator = EdltTemplateSaveValidationStage(issuer)
    candidate = validator.stage(upstream, current_source=raw, metadata=cache,
                                context=context or SaveValidationContext(''))
    return validator, candidate


def dynamic(name='', image=False):
    return SaveValidationContext('', levels=(ValidationLevel(202,42,2,
        (ValidationDynamicVariant(name,image),)),))


def test_blank_pass_order_evidence_no_reload_or_before_save():
    parts = model(); raw, cache, issuer, upstream = parts; before = upstream.as_dict()
    with patch.object(issuer._lifecycle,'load',side_effect=AssertionError('reload')), \
         patch.object(issuer._lifecycle,'prepare_save',side_effect=AssertionError('before save')):
        validator, candidate = stage(parts)
        assert validator.validate(candidate,current_source=raw,metadata=cache,
                                  context=SaveValidationContext('')) is candidate
    result = candidate.as_dict()
    assert result['outcome'] == 'source_predicates_passed'
    assert result['validator_order'] == ['serial','scene_widget','unit']
    assert result['unit']['errors'] == []
    for key in ('model_reloaded','before_save_executed','apply_allowed','saved',
                'target_mutation_attempted','save_dispatched','cache_freshness_verified',
                'original_save_validation_verified'): assert result[key] is False
    assert upstream.as_dict() == before


@pytest.mark.parametrize('text,outcome',[('4096','serial_rejected'),('12x4','unproven_serial_parse')])
def test_serial_stops_before_other_validators(text,outcome):
    _, candidate = stage(model(widget=True),SaveValidationContext(text)); result = candidate.as_dict()
    assert result['outcome'] == outcome
    assert result['validator_order'] == ['serial']
    assert result['scene_widget'] is result['unit'] is None
    assert result['consumed_facts'] == []


def test_widget_rejection_label_status_reports_skip_unit():
    _, candidate = stage(model(widget=True)); result = candidate.as_dict()
    assert result['outcome'] == 'scene_widget_rejected'
    assert result['validator_order'] == ['serial','scene_widget']
    assert result['unit'] is None
    expected = [{'widget':6,'variant':0,'mode':'text','scenes':[1]}]
    assert result['scene_widget']['label_errors'] == expected
    assert result['scene_widget']['status_errors'] == expected
    assert result['scene_widget']['original_dialog_required'] is True
    assert result['scene_widget']['original_dialog_result_consumed'] is False


def test_cycle_normalization_refuses_without_mutating_source():
    parts = model(widget=True,changes={'Widget6WidgetByteValue14':'0x9','Widget6WidgetByteValue15':'0x2'})
    before = dict(parts[0]); _, candidate = stage(parts); result = candidate.as_dict()
    assert result['outcome'] == 'requires_validation_mutation'
    assert result['stop']['first_invalid_byte'] == 14
    assert result['stop']['original_operation'] == 'SceneCycle trailing byte normalization'
    assert parts[0] == before


@pytest.mark.parametrize('context,outcome',[(SaveValidationContext(''),'required_fact_missing'),
    (dynamic(),'source_predicates_passed'),(dynamic(image=True),'scene_widget_rejected')])
def test_existing_action_requires_dynamic_facts(context,outcome):
    _, candidate = stage(model(widget=True,scenes=((1,42,2,26),)),context)
    result = candidate.as_dict(); assert result['outcome'] == outcome
    if outcome == 'required_fact_missing': assert result['stop']['field'] == 'complete ordered DynamicAll'


@pytest.mark.parametrize('name,outcome',[(None,'source_predicates_passed'),('', 'expected_original_exception')])
def test_null_name_lazily_skips_invalid_status_variant(name,outcome):
    parts = model(widget=True,scenes=((1,42,2,26),),changes={
        'Widget6WidgetByteValue1':'0x17','Widget6WidgetByteValue12':'0x63'})
    _, candidate = stage(parts,dynamic(name)); assert candidate.as_dict()['outcome'] == outcome


def test_status_only_still_checks_label_variant():
    parts = model(widget=True,scenes=((1,42,2,26),),changes={
        'Widget6WidgetByteValue1':'0x6','Widget6WidgetByteValue11':'0x63'})
    _, candidate = stage(parts,dynamic()); result = candidate.as_dict()
    assert result['outcome'] == 'expected_original_exception'
    assert result['stop']['original_exception'] == 'DynamicAll index access'


def test_minus_one_selector_requires_setter_but_serial_failure_skips():
    parts = model(widget=True,scenes=((1,42,2,26),),cache_mode='missing-level2')
    assert parts[3].loaded.scenes[0].action_selector == -1
    _, candidate = stage(parts); result = candidate.as_dict()
    assert result['outcome'] == 'requires_validation_mutation'
    assert 'setter(-1)' in result['stop']['original_operation']
    _, candidate = stage(parts,SaveValidationContext('4096'))
    assert candidate.as_dict()['consumed_facts'] == []


def test_corridor_precedes_scene_error_with_exact_clauses():
    parts = model(scenes=((1,42,2,26),(2,42,2,26)),changes={
        'Widget6WidgetType':'0x2','Widget6WidgetByteValue6':'0x2a','CorridorLinkingLinkGroup':'0x2a'})
    _, candidate = stage(parts,SaveValidationContext('',group_names=(ValidationGroupName(56,42,'Hall'),)))
    result = candidate.as_dict(); assert result['outcome'] == 'unit_rejected'
    assert result['unit']['errors'] == [
        'The selected Corridor Link Group "Hall" is also being used in at least one key function. '
        "To resolve this error, either change the Corridor Link Group or remove it's associated key functions.",
        'The following problems were detected with the scene configurations: '
        '\n\nMultiple scenes have been assigned with identical Trigger Group and Action Selector combinations.'
        '\n\nMultiple scenes have been assigned identical scene labels.']
    assert result['unit']['warning_ids'] == ['duplicate-trigger-action','duplicate-name']


@pytest.mark.parametrize('changes',[{'serial_text':None},{'group_names':[]},{'levels':[]},
    {'levels':(ValidationLevel(202,42,2,(ValidationDynamicVariant('',1),)),)},
    {'group_names':(ValidationGroupName(56,42,''),ValidationGroupName(56,42,'x'))},
    {'levels':(ValidationLevel(202,42,2,()),ValidationLevel(202,42,2,()))}])
def test_malformed_context_refused(changes):
    with pytest.raises((EdltError, EdltTemplateError)): SaveValidationContext(**{'serial_text':'',**changes})


def test_issuance_foreign_replace_source_cache_context_and_tamper_guards():
    parts = model(); raw,cache,issuer,upstream = parts; validator,candidate = stage(parts)
    options = dict(current_source=raw,metadata=cache,context=SaveValidationContext(''))
    for bad in (replace(candidate),candidate.as_dict(),None):
        with pytest.raises((EdltError, EdltTemplateError)): validator.validate(bad,**options)
    foreign, other = stage(parts)
    with pytest.raises((EdltError, EdltTemplateError)): foreign.validate(candidate,**options)
    with pytest.raises((EdltError, EdltTemplateError)): validator.validate(other,**options)
    cache_doc = metadata()['lifecycle']; cache_doc['groups'][0]['levels'] = [0]
    for changes in ({'current_source':{**raw,'UnitAddress':'0x15'}},
                    {'metadata':LifecycleCache.from_dict(cache_doc)},
                    {'context':SaveValidationContext('1')},{'dirty_parameters':('UnitAddress',)}):
        with pytest.raises((EdltError, EdltTemplateError)): validator.validate(candidate,**{**options,**changes})
    object.__setattr__(candidate,'projection','{}')
    with pytest.raises((EdltError, EdltTemplateError)): validator.validate(candidate,**options)
    fresh = EdltTemplateSaveValidationStage(issuer)
    with pytest.raises(TemplateSaveValidationStageError): fresh.stage(replace(upstream),**options)
    assert fresh.candidate is None


def test_single_use_cancel_and_apply_do_not_access_target():
    parts = model(); raw,cache,issuer,upstream = parts; validator,candidate = stage(parts)
    options = dict(current_source=raw,metadata=cache,context=SaveValidationContext(''))
    with pytest.raises((EdltError, EdltTemplateError)): validator.stage(upstream,**options)
    class Target:
        def __getattribute__(self,name): raise AssertionError('target accessed')
    for obj in (validator,candidate):
        with pytest.raises(TemplateSaveValidationApplyRefused) as caught: obj.apply(Target())
        assert caught.value.details['target_mutation_attempted'] is False
    assert validator.cancel()['upstream_issuer_cancelled'] is False
    assert validator.state == 'cancelled' and validator.candidate is None
    assert issuer.validate(upstream,raw,metadata=cache) is upstream
    with pytest.raises((EdltError, EdltTemplateError)): validator.validate(candidate,**options)


@pytest.mark.parametrize('error',[RuntimeError('fault'),KeyboardInterrupt('stop'),SystemExit(2)])
def test_faults_interruptions_never_publish_partial_candidates(error):
    parts = model(); raw,cache,issuer,upstream = parts; validator = EdltTemplateSaveValidationStage(issuer)
    with patch('cbus_toolkit.edlt_template_save_validation._Projection.run',side_effect=error) as run:
        with pytest.raises(TemplateSaveValidationStageError if isinstance(error,Exception) else type(error)):
            validator.stage(upstream,current_source=raw,metadata=cache,context=SaveValidationContext(''))
    assert run.call_count == 1
    assert validator.state == 'failed' and validator.candidate is None
    assert validator.last_failure['phase'] == 'ordered_source_predicates'
    assert validator.last_failure['candidate_published'] is False
    assert validator.last_failure['automatic_retries'] == 0
    assert validator.last_failure['target_mutation_attempted'] is False
    assert issuer.validate(upstream,raw,metadata=cache) is upstream


@pytest.mark.parametrize('token,outcome',[('255','requires_validation_mutation'),
    ('0xff','requires_validation_mutation'),('0xFF','source_predicates_passed')])
def test_scene_cycle_requires_exact_trailing_token_fixed_point(token,outcome):
    parts = model(widget=True,scenes=((1,42,2,26),),changes={
        'Widget6WidgetByteValue14':'0x9','Widget6WidgetByteValue15':token})
    _, candidate = stage(parts,dynamic())
    assert candidate.as_dict()['outcome'] == outcome


@pytest.mark.parametrize('token',['255','0xff'])
def test_first_invalid_cycle_byte_does_not_require_token_normalization(token):
    parts = model(widget=True,scenes=((1,42,2,26),),changes={'Widget6WidgetByteValue14':token})
    before = dict(parts[0]); _, candidate = stage(parts,dynamic())
    assert candidate.as_dict()['outcome'] == 'source_predicates_passed'
    assert parts[0] == before


def test_context_mutation_during_predicates_discards_local_projection():
    from cbus_toolkit import edlt_template_save_validation as module
    parts = model(); raw,cache,issuer,upstream = parts
    validator = EdltTemplateSaveValidationStage(issuer); context = SaveValidationContext('')
    original = module._Projection.run
    def mutate(projection):
        result = original(projection)
        object.__setattr__(context,'serial_text','1')
        return result
    with patch.object(module._Projection,'run',autospec=True,side_effect=mutate):
        with pytest.raises(TemplateSaveValidationStageError,match='context changed'):
            validator.stage(upstream,current_source=raw,metadata=cache,context=context)
    assert validator.candidate is None and validator.state == 'failed'
    assert validator.last_failure['phase'] == 'projection_validation'


def test_second_upstream_check_failure_discards_result_without_retry():
    parts = model(); raw,cache,issuer,upstream = parts
    validator = EdltTemplateSaveValidationStage(issuer); original = issuer.validate; calls = []
    def fail_second(*args,**kwargs):
        calls.append(1)
        if len(calls) == 2: raise EdltError('changed upstream')
        return original(*args,**kwargs)
    with patch.object(issuer,'validate',side_effect=fail_second):
        with pytest.raises(TemplateSaveValidationStageError,match='changed upstream'):
            validator.stage(upstream,current_source=raw,metadata=cache,context=SaveValidationContext(''))
    assert len(calls) == 2
    assert validator.candidate is None
    assert validator.last_failure['phase'] == 'projection_validation'
    with pytest.raises((EdltError,EdltTemplateError)):
        validator.stage(upstream,current_source=raw,metadata=cache,context=SaveValidationContext(''))


def test_cancel_during_staging_refused_and_no_candidate_published():
    parts = model(); raw,cache,issuer,upstream = parts
    validator = EdltTemplateSaveValidationStage(issuer)
    def cancel(_projection):
        assert validator.candidate is None and validator.state == 'staging'
        return validator.cancel()
    with patch('cbus_toolkit.edlt_template_save_validation._Projection.run',autospec=True,side_effect=cancel):
        with pytest.raises(TemplateSaveValidationStageError,match='Cannot cancel'):
            validator.stage(upstream,current_source=raw,metadata=cache,context=SaveValidationContext(''))
    assert validator.candidate is None and validator.state == 'failed'


def test_upstream_retained_graph_and_specification_tamper_refused():
    parts = model(); raw,cache,issuer,upstream = parts
    validator,candidate = stage(parts)
    scene = upstream.loaded.scenes[0]
    object.__setattr__(scene,'name_index',0)
    with pytest.raises((EdltError,EdltTemplateError)):
        validator.validate(candidate,current_source=raw,metadata=cache,context=SaveValidationContext(''))
    parts = model(); raw,cache,issuer,upstream = parts
    validator,candidate = stage(parts)
    issuer._source_spec.parameters['UnitAddress'].fields['DefaultValue'] = '$15'
    with pytest.raises((EdltError,EdltTemplateError)):
        validator.validate(candidate,current_source=raw,metadata=cache,context=SaveValidationContext(''))


def test_combined_lifecycle_issuance_and_upstream_cancel():
    raw, cache, _, _ = model()
    source = TemplatePpSnapshot([(name, value.split(' '), False) for name, value in raw.items()])
    issuer = EdltTemplateLifecycleStage(fixture())
    upstream = issuer.stage(template([('Widget6WidgetType', '0x0')]), source=source, metadata=cache)
    validator = EdltTemplateSaveValidationStage(issuer)
    context = SaveValidationContext('4095')
    candidate = validator.stage(upstream, current_source=source, metadata=cache, context=context)
    assert candidate.as_dict()['outcome'] == 'source_predicates_passed'
    assert validator.validate(candidate, current_source=source, metadata=cache, context=context) is candidate
    with pytest.raises(EdltTemplateError):
        validator.validate(candidate, current_source=source, metadata=cache, context=context,
                           dirty_parameters=('UnitAddress',))
    issuer.cancel()
    with pytest.raises(EdltTemplateError):
        validator.validate(candidate, current_source=source, metadata=cache, context=context)


def test_group_acquisition_runs_even_with_unused_corridor():
    from cbus_toolkit.edlt_lifecycle import LifecycleGroup
    raw, cache, issuer, _ = model(changes={
        'Widget6WidgetType': '0x2', 'Widget6WidgetByteValue6': '0x2a'})
    cache = LifecycleCache(cache.applications, tuple(
        LifecycleGroup(56, 42, False) if (row.application, row.group) == (56, 42) else row
        for row in cache.groups))
    upstream = issuer.stage(raw, metadata=cache)
    _, candidate = stage((raw, cache, issuer, upstream))
    result = candidate.as_dict()
    assert result['outcome'] == 'requires_validation_mutation'
    assert result['stop']['validator'] == 'unit'
    assert result['stop']['reason'] == 'Widget GetGroup 6'
    assert upstream.after_load['CorridorLinkingLinkGroup'] == (255,)


def test_unit_outer_skip_avoids_unread_minus_one_setter():
    parts = model(scenes=((1, 255, 255, 255), (2, 42, 2, 26)), cache_mode='missing-level2')
    raw, cache, issuer, _ = parts
    # One output in scene 1 sets both missing flags. The later editable -1
    # action would have setter effects, but the original outer skip avoids it.
    raw['SceneBucket'] = ' '.join(hex(value) for value in
        [2, 1, 255, 255, 255, 0, 12, 1, 2, 0, 42, 2, 26] + [255] * 219)
    raw['Scene2StartAddress'] = '0x8'
    upstream = issuer.stage(raw, metadata=cache)
    assert upstream.loaded.scenes[1].action_selector == -1
    _, candidate = stage((raw, cache, issuer, upstream))
    result = candidate.as_dict()
    assert result['outcome'] == 'unit_rejected'
    assert result['unit']['skipped_scene_indices'] == list(range(1, 8))
    assert result['unit']['warning_ids'] == ['populated-missing-trigger-action', 'populated-missing-name']
