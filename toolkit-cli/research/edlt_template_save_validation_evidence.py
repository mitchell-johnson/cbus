"""Sanitized synthetic source-predicate receipts; no vendor or target execution.

Run from toolkit-cli with PYTHONPATH=src:tests:. and an exclusive output path.
The synthetic schema is reused from narrow guard tests, not a vendor oracle.
"""
import argparse
import hashlib
import json
from pathlib import Path

from cbus_toolkit.edlt import _render
from cbus_toolkit.edlt_lifecycle import LifecycleCache
from cbus_toolkit.edlt_reset import _RawState
from cbus_toolkit.edlt_template_model_stage import EdltTemplateModelStage
from cbus_toolkit.edlt_template_save_validation import (
    EdltTemplateSaveValidationStage, SaveValidationContext, ValidationDynamicVariant,
    ValidationGroupName, ValidationLevel,
)
from tests.test_edlt_lifecycle import scene_values
from tests.test_edlt_reset import fixture, metadata


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_RECEIPTS = (
    'research/edlt_template_terminal_evidence.json',
    'research/edlt_template_terminal_native_attempt1.json',
    'research/fixtures/edlt-template-original-vectors.json',
    'research/fixtures/edlt-template-original-acceptance.json',
    'research/fixtures/edlt-template-model-original-vectors.json',
    'research/fixtures/edlt-template-model-original-acceptance.json',
    'research/fixtures/edlt-template-reset-prelude-original-acceptance.json',
)
INPUTS = (
    'src/cbus_toolkit/edlt_template_save_validation.py',
    'src/cbus_toolkit/edlt_template_save_predicates.py',
    'research/edlt_template_save_validation_source.json',
    'research/edlt_template_serial_validation_source.json',
    'research/edlt_template_scene_widget_validation_source.md',
    'research/edlt_template_unit_validation_source.md',
    'research/edlt_template_unit_validation_source.json',
    'tests/test_edlt_reset.py', 'tests/test_edlt_lifecycle.py',
)


def fingerprints(paths):
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}


def run():
    pins, history = fingerprints(INPUTS), fingerprints(HISTORICAL_RECEIPTS)
    cases = []
    definitions = (
        ('blank-accepted', '4095', {}, None, (), (), 'source_predicates_passed'),
        ('serial-rejected', '4096', {}, None, (), (), 'serial_rejected'),
        ('culture-unproved', '+001', {}, None, (), (), 'unproven_serial_parse'),
        ('corridor-rejected', '4095', {'Widget6WidgetType': '2',
            'Widget6WidgetByteValue6': '42', 'CorridorLinkingLinkGroup': '42'}, None,
            (ValidationGroupName(56, 42, 'Synthetic first group'),), (), 'unit_rejected'),
        ('trailing-raw-normalization', '4095', {'Widget6WidgetType': '6',
            'Widget6WidgetByteValue1': '16', 'Widget6WidgetByteValue13': '9',
            'Widget6WidgetByteValue14': '255'}, None, (), (), 'requires_validation_mutation'),
        ('dynamic-facts-unknown', '4095', {'Widget6WidgetType': '6',
            'Widget6WidgetByteValue1': '16', 'Widget6WidgetByteValue13': '0'},
            (2, 0, 42, 2, 26), (), (), 'required_fact_missing'),
        ('dynamic-text-image-conflict', '4095', {'Widget6WidgetType': '6',
            'Widget6WidgetByteValue1': '16', 'Widget6WidgetByteValue13': '0',
            'Widget6WidgetByteValue11': '0'}, (2, 0, 42, 2, 26), (),
            (ValidationLevel(202, 42, 2, (ValidationDynamicVariant('', True),)),),
            'scene_widget_rejected'),
        ('null-name-skips-status-index', '4095', {'Widget6WidgetType': '6',
            'Widget6WidgetByteValue1': '23', 'Widget6WidgetByteValue13': '0',
            'Widget6WidgetByteValue11': '0', 'Widget6WidgetByteValue12': '99'},
            (2, 0, 42, 2, 26), (),
            (ValidationLevel(202, 42, 2, (ValidationDynamicVariant(None, True),)),),
            'source_predicates_passed'),
        ('empty-name-checks-status-index', '4095', {'Widget6WidgetType': '6',
            'Widget6WidgetByteValue1': '23', 'Widget6WidgetByteValue13': '0',
            'Widget6WidgetByteValue11': '0', 'Widget6WidgetByteValue12': '99'},
            (2, 0, 42, 2, 26), (),
            (ValidationLevel(202, 42, 2, (ValidationDynamicVariant('', True),)),),
            'expected_original_exception'),
    )
    for name, serial, overrides, header, group_names, levels, expected in definitions:
        spec = fixture()
        raw = _RawState(spec.defaults()).raw()
        raw.update(overrides)
        if header is not None:
            raw.update({name: _render(value) for name, value in scene_values(header).items()})
        cache = LifecycleCache.from_dict(metadata()['lifecycle'])
        model = EdltTemplateModelStage(spec)
        upstream = model.stage(raw, metadata=cache)
        before = upstream.as_dict()
        context = SaveValidationContext(serial, group_names, levels)
        issuer = EdltTemplateSaveValidationStage(model)
        receipt = issuer.stage(upstream, current_source=raw, metadata=cache, context=context)
        assert issuer.validate(receipt, current_source=raw, metadata=cache, context=context) is receipt
        assert before == upstream.as_dict()
        result = receipt.as_dict()
        assert result['outcome'] == expected, (name, result['outcome'], expected)
        for field in ('original_save_validation_verified', 'apply_allowed', 'target_mutation_attempted',
                      'save_dispatched', 'saved', 'physical_device_verified'):
            assert result[field] is False
        # Full PP images remain in their upstream stage; this exported evidence
        # contains only synthetic diagnostics and fingerprint provenance.
        cases.append({'case': name, 'expected_outcome_from_source_contract': expected,
                      'upstream_unchanged': True, 'receipt': result})
    assert pins == fingerprints(INPUTS)
    assert history == fingerprints(HISTORICAL_RECEIPTS)
    return {'format': 'cbus-edlt-template-save-validation-offline-evidence-v1',
        'evidence_class': 'synthetic software execution of source predicates',
        'schema_scope': 'owned synthetic exact-size KEYGL5 guard schema; not vendor defaults',
        'input_sha256': pins, 'historical_receipt_sha256': history,
        'inputs_and_historical_receipts_unchanged': True, 'cases': cases,
        'passed': True, 'original_validator_runtime_executed': False,
        'original_assemblies_loaded': False, 'original_ui_executed': False,
        'native_io_executed': False, 'physical_device_verified': False,
        'apply_allowed': False, 'saved': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Reserve the path exclusively before running; a partial failure leaves no
    # misleading passed report and existing evidence cannot be overwritten.
    with args.output.open('x') as output:
        evidence = run()
        output.write(json.dumps(evidence, indent=2, ensure_ascii=True) + '\n')
    print(json.dumps({'output': str(args.output), 'passed': evidence['passed'],
                      'case_count': len(evidence['cases'])}))


if __name__ == '__main__':
    main()
