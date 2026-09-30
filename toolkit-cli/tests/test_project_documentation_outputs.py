"""Bounded extra output profiles and native non-dimmer documentor exits."""
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_outputs as outputs
from test_project_documentation import application, build, group, network, unit

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/experiments/2026-09-30/project-documentor-outputs-static.json'


def fixture(kind, firmware='2.7.00', *, consumed=True):
    groups = [1, 2] + [255] * 10 + [2, 255, 255, 255]
    pps = [('Application', '56 255')]
    if consumed:
        pps += [('GroupAddress', ' '.join(map(str, groups))),
                ('LogicFunction', '1 0 0 0 0 0 0 0')]
        pps += [(f'LogicGA{index}Associations', '1 0 0 0 0 0 0 0' if index == 13 else '0 0 0 0 0 0 0 0')
                for index in range(13, 17)]
    model = build([network(254, 'Local', apps=(application(56, 'Lighting', (group(1, 'Lamp'), group(2, 'Logic'))),),
                           units=(unit(1, kind, firmware=firmware, pps=pps),))])
    return model, model.networks[0], model.networks[0].units[0]


@pytest.mark.parametrize('kind,count', outputs.DIRECT_CHANNELS.items())
def test_additional_native_output_table(kind, count):
    model, net, subject = fixture(kind)
    out = doc._Writer()
    record = doc.document_unit(out, net, subject, model)
    rows = [line for line in out.lines if line.startswith('<tr><td>')]
    assert record['status'] == 'recovered'
    assert len(rows) == count
    assert rows[0] == ('<tr><td>1</td><td><a href="#254_56_1">Lamp</a>, '
                       '<a href="#254_56_2">Logic</a></td><td>Max</td></tr>')
    if count > 1:
        assert rows[1] == '<tr><td>2</td><td><a href="#254_56_2">Logic</a></td><td>&nbsp;</td></tr>'
    assert not out.unrecovered


@pytest.mark.parametrize('kind', outputs.DIRECT_CHANNELS)
def test_new_output_profiles_require_consumed_pp(kind):
    model, net, subject = fixture(kind, consumed=False)
    out = doc._Writer()
    assert doc.document_unit(out, net, subject, model)['status'] == 'partial'
    assert out.unrecovered
    assert not any(line.startswith('<table') for line in out.lines)


@pytest.mark.parametrize('kind', outputs.NCC_TYPES)
def test_native_ncc_body_is_intentionally_base_only(kind):
    model, net, subject = fixture(kind, '1.3.0', consumed=False)
    out = doc._Writer()
    base = doc._Writer()
    doc.document_base(base, net, subject)
    assert doc.document_output(out, net, subject) == 'recovered'
    assert out.lines == base.lines
    assert out.unrecovered == []


@pytest.mark.parametrize('kind', ['DIMDD4', 'DIMDD4F', 'DIMDD8', 'DIMDD8F'])
def test_earlier_dimdd_is_a_different_unrecovered_class(kind):
    _, net, subject = fixture(kind, '1.2.99')
    assert outputs.output_base_only(subject) is False
    out = doc._Writer()
    assert doc.document_output(out, net, subject) == 'partial'
    assert out.unrecovered


@pytest.mark.parametrize('firmware', ['', 'unknown', '9.0.1', '10', '9' * 5000, '2147483648'])
def test_new_profiles_do_not_infer_missing_or_unregistered_identity(firmware):
    _, _, direct = fixture('ANODN4', firmware)
    _, _, ncc = fixture('DIMDD4', firmware)
    assert outputs.output_profile(direct) is None
    assert outputs.output_base_only(ncc) is False


def test_existing_marshalling_profile_is_preserved():
    _, _, subject = fixture('RELDN8')
    assert outputs.output_profile(subject).indices == (1, 2, 3, 4, 7, 8, 9, 10)
    assert outputs.output_profile(replace(subject, unit_type='RELDN8SP')) is None


def test_extra_output_receipt_and_runtime_binding():
    receipt = json.loads(RECEIPT.read_text())
    assert len(receipt['checks']) == 55
    assert all(receipt['checks'].values())
    assert receipt['original_executed'] is False
    assert receipt['original_generated_page_comparison'] == 'not_obtained'
    assert receipt['model_module_sha256'] == hashlib.sha256(Path(outputs.__file__).read_bytes()).hexdigest()
    assert {row['unit_type'] for row in receipt['profiles'] if row.get('report_channels')} == set(outputs.DIRECT_CHANNELS)


def test_extra_output_receipt_regenerates_from_pinned_original():
    exe = os.environ.get('CBUS_TOOLKIT_EXE')
    if not exe:
        pytest.skip('Pinned original EXE required for static receipt regeneration')
    path = ROOT / 'research/project_documentor_outputs_static.py'
    import sys
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('project_documentor_outputs_static', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.inspect(Path(exe), Path(exe).with_suffix('.map')) == json.loads(RECEIPT.read_text())
