"""Wave33 narrow pins: architectural DocumentHTML guards with zero prior refs.

Offline only: literal fixture snapshot + in-memory Network/Unit, no broker.
Covers project_documentation_architectural.py branches not directly asserted
elsewhere (whole-body equality aside): LINE() vs scaled volts, unclosed
logic cell + kickstart gate, DMX disabled/take-vs-update + enable gate,
loss-fade vs plain special + cross-fade branches, C-Bus lock link + mask
column gate.
"""
from copy import deepcopy
import json
from pathlib import Path

from cbus_toolkit import project_documentation as doc
from cbus_toolkit import project_documentation_architectural as body

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / 'research/fixtures/project-documentor-architectural-literal.json'
CASES = json.loads(VECTOR.read_text())['cases']


def unit(row=None, **changes):
    row = row or CASES[0]
    pp = deepcopy(row['parameters'])
    pp.update(changes)
    return doc.Unit(row['address'], row['id'], row['unit_type'], '', '', row['firmware'], '', {
        k: v if isinstance(v, str) else ' '.join(map(str, v)) for k, v in pp.items() if v is not None}, {})


def network():
    raw = json.loads(VECTOR.read_text())['network']
    return doc.Network(raw['address'], raw['name'], '', '', [
        doc.Application(a['address'], a['name'], '', [doc.Group(g['address'], g['name'], '', [
            doc.Level(l['address'], l['name'], l['value']) for l in g['levels']]) for g in a['groups']])
        for a in raw['applications']], [])


def test_full_line_voltage_uses_line_marker_while_scaled_is_bare():
    lines = body.architectural_body_lines(network(), unit(CASES[0]))
    assert '<td>LINE(240)</td>' in lines[3]
    assert '<td>51</td>' in lines[4]
    assert '<td>60</td>' in lines[5]
    assert 'LINE(51)' not in ''.join(lines) and 'LINE(60)' not in ''.join(lines)


def test_unclosed_logic_cell_and_fan_kickstart_gate():
    lines = body.architectural_body_lines(network(), unit(CASES[0]))
    assert '<td>Max<td>Fan Control</td><td>12 s</td>' in lines[3]
    assert '<td>Min<td>Dimming Curve A</td><td>&nbsp;</td>' in lines[4]
    assert '&nbsp;<td>Linear (1:1)</td><td>&nbsp;</td>' in lines[5]


def test_dmx_disabled_marker_take_vs_update_and_enable_gate():
    full = ''.join(body.architectural_body_lines(network(), unit(CASES[0])))
    assert '<td>&lt;DMX Disabled&gt;</td>' in full
    assert '<td>Take C-Bus</td>' in full
    assert '<td>Update C-Bus</td>' in full
    assert '<th>Enable Fade Time</th>' in full
    empty = ''.join(body.architectural_body_lines(network(), unit(CASES[1])))
    assert '<tr><th>Channel</th><th>DMX</th></tr>' in empty
    assert 'Enable Fade Time' not in empty
    assert '<td>&lt;DMX Disabled&gt;</td>' in empty


def test_loss_fade_vs_plain_special_and_scene_fade_branches():
    text = ''.join(body.architectural_body_lines(network(), unit(CASES[0])))
    assert 'C-Bus Loss</td><td><table border="1"><tr><th>Fade Time</th></tr><tr><td>8 s</td></tr></table>' in text
    assert 'Panic/Dry Contact 1 (aux1)</td><td>&nbsp;</td>' in text
    assert '<td>0d 0h 2m 0 s</td>' in text
    assert '<tr><td>Final</td><td>&nbsp;</td><td>&nbsp;</td>' in text


def test_cbus_lock_enable_link_and_mask_column_gate():
    full = body.architectural_body_lines(network(), unit(CASES[0]))
    assert full[0] == 'C-Bus Lock Enable Group: <a href="#254_203_4">G4</a><br />'
    assert '<th>C-Bus Mask 1</th><th>C-Bus Mask 2</th><th>C-Bus Mask 3</th><th>C-Bus Mask 4</th>' in full[2]
    assert full[3].endswith('<td>Yes</td><td>&nbsp;</td><td>Yes</td><td>&nbsp;</td></tr>')
    assert full[4].endswith('<td>&nbsp;</td><td>Yes</td><td>Yes</td><td>&nbsp;</td></tr>')
    empty = body.architectural_body_lines(network(), unit(CASES[1]))
    assert empty[0] == 'C-Bus Lock Enable Group: Unused<br />'
    assert 'C-Bus Mask' not in empty[2]
    assert 'Yes' not in ''.join(empty)
