"""Independent literal vectors for the recovered original bridge documentor."""
import pytest

from test_project_documentation import application, build, network, page, unit


def bridge(*, apps='56 202', adjacent='1', count='1', route='2 3 255', extra=()):
    pp = [('Application', apps), ('ApplicationConnectEnabled', adjacent), ('BridgeCount', count)]
    if route is not None:
        pp.append(('BridgeAddress', route))
    return unit(1, 'BRIDGE2N', firmware='1.4.00', pps=tuple(pp) + extra)


def document(device, others=(1, 2, 3)):
    apps = (application(56, 'Lighting'), application(202, 'Trigger Control'))
    return page([network(254, 'Local', apps=apps, units=(device,))]
                + [network(n, f'N{n}') for n in others])


def test_bridge_application_lists_adjacent_and_destination_literal_order():
    lines, summary = document(bridge())
    start = lines.index('Adjacent Network: <a href="#1">N1</a><br/>')
    assert lines[start:start + 5] == [
        'Adjacent Network: <a href="#1">N1</a><br/>',
        'Connect Application 1: <a href="#254_56">Lighting</a><br/>',
        'Connect Application 2: <a href="#254_202">Trigger Control</a><br/>',
        'Send Messages to Adjacent Network: Yes<br/>',
        'Send Messages to Remote Network: <a href="#3">N3</a><br/>',
    ]
    assert summary['units'][0]['status'] == 'recovered'


@pytest.mark.parametrize('route, expected', [
    ('2 3 255', '<a href="#3">N3</a>'),
    ('2 99 3', '<a href="#2">N2</a>'),
    ('255 3', 'Unknown Network'),
    ('99 3', 'Unknown Network'),
    ('', 'Unknown Network'),
    ('2', '<a href="#2">N2</a>'),
    ('2 2 2 2 2 2 2 3', '<a href="#2">N2</a>'),
])
def test_bridge_route_is_contiguous_known_prefix_of_seven_not_count_entries(route, expected):
    lines, _ = document(bridge(count='1', route=route))
    assert f'Send Messages to Remote Network: {expected}<br/>' in lines


def test_bridge_private_application_255_names_and_disabled_forwarding():
    lines, summary = document(bridge(apps='255 255', adjacent='0', count='0', route=None))
    assert 'Connect Application 1: All Applications<br/>' in lines
    # This unescaped original string is deliberately not modernized.
    assert 'Connect Application 2: <Unused><br/>' in lines
    assert 'Send Messages to Adjacent Network: No<br/>' in lines
    assert 'Send Messages to a Remote Network: No<br/>' in lines
    assert summary['units'][0]['status'] == 'recovered'


def test_bridge_missing_destination_is_unknown_programming_not_unknown_network():
    lines, summary = document(bridge(route=None))
    assert 'Bridge destination network: not documented (unrecovered)<br />' in lines
    assert 'Send Messages to Remote Network: Unknown Network<br/>' not in lines
    assert summary['units'][0]['status'] == 'partial'


@pytest.mark.parametrize('kwargs', [dict(apps='56'), dict(adjacent='2'), dict(count='8')])
def test_bridge_incomplete_or_invalid_fields_do_not_claim_recovered(kwargs):
    lines, summary = document(bridge(**kwargs))
    assert 'Bridge connection settings: not documented (unrecovered)<br />' in lines
    assert summary['units'][0]['status'] == 'partial'


def test_bridge_missing_far_side_stops_before_forwarding_fields():
    lines, summary = document(bridge(), others=(2, 3))
    assert 'WARNING: BRIDGE2N has no far side Network.' in lines
    assert not any(line.startswith('Connect Application') for line in lines)
    assert summary['units'][0]['status'] == 'recovered'


def test_bridge_documenting_never_changes_snapshot():
    from cbus_toolkit.project_documentation import render
    from test_project_documentation import WHEN
    model = build([network(254, 'Local', units=(bridge(),)), network(1, 'Far')])
    before = dict(model.by_address[254].units[0].parameters)
    first = render(model, generated=WHEN)
    assert render(model, generated=WHEN) == first
    assert model.by_address[254].units[0].parameters == before


def test_bridge_source_receipt_checks_are_pinned():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    receipt = json.loads((root / 'research/experiments/2026-09-30/project-documentor-bridge-static.json').read_text())
    assert receipt['original_executed'] is False
    assert all(receipt['checks'].values())
    assert len(receipt['bridge_registrations']) == 7
    assert len(receipt['method_spans']) == 15


def test_bridge_private_source_reproduces_receipt():
    import json
    import os
    from pathlib import Path
    import sys
    source = os.environ.get('CBUS_TOOLKIT_EXE')
    if not source:
        pytest.skip('Set CBUS_TOOLKIT_EXE to verify pinned original bridge methods')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'research'))
    from project_documentor_bridge_static import inspect
    exe = Path(source)
    actual = inspect(exe, Path(os.environ.get('CBUS_TOOLKIT_MAP', exe.with_suffix('.map'))))
    expected = json.loads((root / 'research/experiments/2026-09-30/project-documentor-bridge-static.json').read_text())
    assert json.loads(json.dumps(actual)) == expected
