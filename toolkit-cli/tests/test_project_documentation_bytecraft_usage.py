"""Old Bytecraft output channel identity and refusal boundaries."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

from cbus_toolkit.project_documentation import Unit
from cbus_toolkit.project_documentation_bytecraft_usage import bytecraft_output_group_usage

FIXTURE = Path(__file__).parents[1] / 'research/fixtures/project-documentor-bytecraft-usage-static.json'


def unit(firmware='1.9.02', kind='DIMPR12', **changes):
    pp = {'Application': '56', 'GroupAddress': '8 9 8 255 10 11 12 13 14 15 16 8'}
    pp.update(changes)
    return Unit(1, 'Dimmer', kind, kind, '', firmware, '',
                {name: value for name, value in pp.items() if value is not None}, {})


def test_channel_order_duplicates_and_unused_identity():
    assert bytecraft_output_group_usage(unit(), 56, 8).html == 'Channel 1<br/>Channel 3<br/>Channel 12'
    assert bytecraft_output_group_usage(unit(), 56, 255).html == 'Channel 4'
    assert bytecraft_output_group_usage(unit(), 57, 8).html == ''
    assert bytecraft_output_group_usage(unit(), 56, 99).status == 'recovered'


@pytest.mark.parametrize('firmware', ['0', '1.9.01', '1.9.02'])
def test_old_registration_admitted(firmware):
    assert bytecraft_output_group_usage(unit(firmware), 56, 8).status == 'recovered'


@pytest.mark.parametrize('firmware', ['', '1.9.03', '9', '١.٩.٠٢', '1.9.x', None, '2147483648'])
def test_missing_malformed_and_l1_firmware_refused(firmware):
    assert bytecraft_output_group_usage(unit(firmware), 56, 8).status == 'unrecovered'


@pytest.mark.parametrize('kind', ['DIMPR12A', 'DIMPR12L1', 'DIMPR1', 'dimpr12'])
def test_other_native_classes_refused(kind):
    assert bytecraft_output_group_usage(unit(kind=kind), 56, 8).status == 'unrecovered'


@pytest.mark.parametrize('changes', [{'Application': None}, {'Application': ''}, {'Application': '256'},
    {'Application': '56 broken'}, {'GroupAddress': None}, {'GroupAddress': '8 ' * 11},
    {'GroupAddress': '8 ' * 11 + '-1'}, {'GroupAddress': '8 ' * 11 + 'bad'},
    {'GroupAddress': '8 ' * 12 + '256'}])
def test_missing_or_malformed_consumed_pp_fails_closed(changes):
    result = bytecraft_output_group_usage(unit(**changes), 56, 8)
    assert result.status == 'unrecovered' and result.html == '' and result.missing


def test_only_channel_projection_consumed():
    u = unit(PresetRec00='broken', DMXPatchInfo='broken', LogicGroupAddress='8', Application='56 202')
    result = bytecraft_output_group_usage(u, 56, 8)
    assert result.status == 'recovered' and result.html.endswith('Channel 12')
    extra = replace(u, parameters={**u.parameters, 'GroupAddress': u.parameters['GroupAddress'] + ' 8'})
    assert bytecraft_output_group_usage(extra, 56, 8) == result


def test_static_receipt():
    receipt = json.loads(FIXTURE.read_text())
    assert len(receipt['checks']) == 18 and all(receipt['checks'].values())
    assert receipt['registrations'][0][2:] == ['0', '1.9.02']
    assert receipt['original_loader_execution'] == 'not_executed'


def test_generic_dispatch_admits_old_output_only_and_preserves_l1_boundary():
    from cbus_toolkit.project_documentation_usage import group_usage
    assert group_usage(unit(), 56, 8, 'output') == bytecraft_output_group_usage(unit(), 56, 8)
    assert group_usage(unit('1.9.03'), 56, 8, 'output').status == 'unrecovered'
    assert group_usage(unit(), 56, 8, 'input').status == 'unrecovered'
    assert group_usage(unit(), 56, 8, 'other').status == 'partial'


def test_static_receipt_reproduces_when_configured():
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE for pinned Bytecraft static comparison')
    sys.path.insert(0, str(FIXTURE.parents[1]))
    from project_documentor_bytecraft_usage_static import inspect
    exe = Path(source)
    result = inspect(exe, Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map'))))
    assert json.loads(json.dumps(result)) == json.loads(FIXTURE.read_text())
