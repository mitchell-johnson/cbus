"""Interpret pinned original eDLT IL against explicit synthetic control proxies.

Research only. No vendor method, GUI, model callback, service or project is
executed. Source IL determines traversal, order and catch/finally dispatch;
external calls have named proxy implementations, never an inferred PP effect.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


DLL_SHA256 = '75bc741234b52a168a4838fee305c309d3909571d2711f7580216b46b028e8d3'
PINS = {
    'bin/mono-sgen64': '91b99fc4b1158785b43506f2d76f9998c31f0492128e5789fbaaab0e300afd49',
    'lib/mono/4.5/mcs.exe': '857bb3129c3e2a5e7f8410db8fa5eb78139e934bb6279a72428597962311d771',
    'lib/mono/4.5/mscorlib.dll': '86364b7803c92d8c88b590031f015f80b10b00641e9d067e07a529a131d815e4',
    'lib/mono/4.5/System.Web.Extensions.dll': 'c7c6227fe81ced769f27f93f214445dae4af59925499382b1abc16c5b49f69e5',
    'lib/mono/gac/Mono.Cecil/0.11.1.0__0738eb9f132ed756/Mono.Cecil.dll': '2df316dbdc0999b76dcd09029b6c966b8bce8f21845f551d4075daed208f2c38',
}
INTERPRETED = frozenset(('BeforeChangePpAttributes', 'AfterChangePpAttributes',
    'PopulateWidgetPanels', 'SetupForm', 'SetUpControls', 'ResetControlBinding'))
EXPECTED_ROOTS = {
    'BeforeChangePpAttributes': '7ca880302683f99a213d4d043a80035b80548480995c369296e134455835330e',
    'AfterChangePpAttributes': 'a2525622f9056fc60a92117ebde89f0f04d3e9049226dfd8a6ff429e0bcf34fb',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(eq=False)
class Node:
    name: str
    kind: str = 'control'
    fields: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


@dataclass(eq=False)
class Iterator:
    items: list
    index: int = -1


class ProxyFailure(RuntimeError):
    pass


class UnsupportedIL(RuntimeError):
    pass


def label(value):
    if isinstance(value, Node):
        return value.name
    if isinstance(value, Iterator):
        return 'enumerator'
    if isinstance(value, list):
        return 'collection'
    if isinstance(value, Exception):
        return type(value).__name__
    if isinstance(value, dict):
        return value.get('signature', value.get('name', 'metadata'))
    return value


def context():
    nested = Node('nested-radio', 'radio')
    skipped = Node('basewidget-child-combo', 'combo')
    tree = [Node('outer-combo', 'combo', children=[nested]),
            Node('widget-panel', 'basewidget', children=[skipped]),
            Node('plain', children=[Node('plain-child-combo', 'combo')])]
    unit = Node('unit', 'model', fields={
        'PPAttributes': [Node('PP0', 'pp'), Node('PP1', 'pp')],
        'Widgets': [Node('widget' + str(i), 'widget') for i in range(21)],
        'PageWidget': Node('page-widget-model', 'widget'), 'Network': Node('network', 'model')})
    fields = {'_unit': unit, 'RedrawTimer': Node('redraw-timer', 'timer'),
              'bsMainUnit': Node('main-binding', 'binding'),
              '_lWidgetPanels': [Node('old-panel0', 'basewidget'), Node('old-panel1', 'basewidget')],
              'pnlWidgetPanelContainer': Node('panel-container'),
              'flpWidgetPresetLevels': Node('restore-container'),
              'comboBox2': Node('comboBox2', 'combo'), 'dataGridView1': Node('dataGridView1')}
    for name in ('radioButton5', 'radioButton3', 'rbColourIndicatorOffFixedColour',
                 'rbColourIndicatorOnFixedColour', 'radioButton4', 'radioButton6', 'rbRestorePreset'):
        fields[name] = Node(name, 'radio')
    return Node('form', 'form', fields=fields, children=tree)


class VM:
    """Small fail-closed CLI interpreter, bounded to six pinned method bodies."""

    def __init__(self, methods, *, expand=False, fail_at=None, fail_call=None):
        self.methods, self.expand = methods, expand
        self.fail_at, self.fail_call = fail_at, fail_call
        self.trace, self.steps, self.depth = [], 0, 0
        self.calls = 0
        self.fault_fired = False
        self.form = context()

    def call(self, method, receiver, arguments, *, constructor=False):
        self.calls += 1
        event = {'call_index': self.calls, 'method': method['type'] + '::' + method['name'],
                 'receiver': label(receiver), 'arguments': [label(arg) for arg in arguments]}
        self.trace.append(event)
        if not self.fault_fired and (self.calls == self.fail_at or (
                self.fail_call is not None and self.fail_call == (label(receiver), method['name']))):
            self.fault_fired = True
            event['proxy_failure'] = True
            raise ProxyFailure('injected at ' + event['method'])
        name, kind = method['name'], method['type']
        if kind == 'eDLT.FrmBaseUnit' and name in INTERPRETED and self.expand:
            event['dispatch'] = 'interpret_original_il'
            return self.run(name, [receiver, *arguments])
        event['dispatch'] = 'proxy'
        if constructor:
            if name != '.ctor':
                raise UnsupportedIL('Unexpected constructor')
            node = Node('new-' + kind.rsplit('.', 1)[-1] + '-' + str(self.calls),
                        'basewidget' if 'Widget' in kind else 'control')
            if kind == 'eDLT.Controls.PowerRestoreLevelControl':
                node.fields['Level'] = Node(node.name + '.Level')
            return node
        if name == 'GetEnumerator':
            return Iterator(list(receiver))
        if name == 'MoveNext':
            receiver.index += 1
            return receiver.index < len(receiver.items)
        if name == 'get_Current':
            return receiver.items[receiver.index]
        if name == 'get_Controls':
            return receiver.children
        if name == 'get_Count':
            return len(receiver)
        if name == 'get_Item':
            return receiver[arguments[0]]
        if name == 'Clear':
            receiver.clear()
            return None
        if name == 'Add':
            receiver.append(arguments[0])
            return None
        if name == 'Dispose':
            if isinstance(receiver, Node):
                receiver.fields['proxy_disposed'] = True
            return None
        if name == 'get_Message' and isinstance(receiver, Exception):
            return str(receiver)
        if name == 'Concat' and kind == 'System.String':
            return ''.join(arguments)
        if name == 'Show' and kind == 'System.Windows.Forms.MessageBox':
            return 0
        if name == 'get_DataBindings':
            return receiver.fields.setdefault('DataBindings', [])
        if name.startswith('get_'):
            key = name[4:]
            if not isinstance(receiver, Node) or key not in receiver.fields:
                raise UnsupportedIL('Unspecified proxy getter: ' + event['method'])
            return receiver.fields[key]
        if name.startswith('set_'):
            receiver.fields[name[4:]] = arguments[0]
            return None
        if name.startswith('add_'):
            receiver.fields.setdefault(name, []).append(arguments[0])
            return None
        if name in ('Stop', 'Start') and kind == 'System.Timers.Timer':
            receiver.fields['running'] = name == 'Start'
            return None
        # Explicitly opaque calls. They do not execute model, UI, binding,
        # logger, native window, image, validation or persistence behavior.
        opaque = {'AfterLoadPPData', 'PopulatePrimarySecondaryApplication', 'ResetBindings',
            'UpdateNavigationControl', 'ShowSelectedWidget', 'tpKeyFunctions_SelectedIndexChanged',
            'SetupForm', 'SetUpControls', 'ShowWidget', 'ResumeDrawing', 'SetWidgetData',
            'SetUpDataBindings', 'LogException', 'OnFormClosed', 'Invalidate', 'BringToFront', 'Refresh'}
        if name == 'ClearControlsRecursively':
            # Separate destructive recursion is outside this interpreter.
            # The test passes an empty container so there are no omitted nodes.
            if arguments[0].children:
                raise UnsupportedIL('ClearControlsRecursively requires explicit recovery for a nonempty container')
            event['empty_container_precondition'] = True
            return None
        if name in opaque:
            event['opaque_callback'] = True
            return None
        raise UnsupportedIL('No proxy dispatcher for ' + event['method'])

    @staticmethod
    def is_instance(value, kind):
        if value is None:
            return False
        if kind == 'System.IDisposable':
            return isinstance(value, Iterator)
        if kind == 'eDLT.WidgetPanels.baseWidgePanels.BaseWidget':
            return isinstance(value, Node) and value.kind == 'basewidget'
        if kind == 'eDLT.Controls.PPControls.ComboBoxAddEdit':
            return isinstance(value, Node) and value.kind == 'combo'
        if kind == 'eDLT.Controls.PPControls.PPRadioButton':
            return isinstance(value, Node) and value.kind == 'radio'
        if kind == 'System.Windows.Forms.Control':
            return isinstance(value, Node)
        raise UnsupportedIL('Unspecified proxy type test: ' + kind)

    def run(self, name, args=None):
        self.depth += 1
        if self.depth > 64:
            raise UnsupportedIL('Proxy recursion bound exceeded')
        try:
            method = self.methods[name]
            args = args or [self.form]
            return self.execute(method, args, [None] * method['locals'], 0)
        finally:
            self.depth -= 1

    def execute(self, method, args, locals_, start, *, finally_block=False):
        instructions = {row['offset']: row for row in method['instructions']}
        following = {row['offset']: (method['instructions'][i+1]['offset']
                     if i+1 < len(method['instructions']) else method['il_size'])
                     for i, row in enumerate(method['instructions'])}
        stack, ip = [], start
        def handlers(offset):
            return sorted((h for h in method['handlers']
                           if h['try_start'] <= offset < h['try_end']),
                          key=lambda h: h['try_end'] - h['try_start'])
        while ip < method['il_size']:
            self.steps += 1
            if self.steps > 20000:
                raise UnsupportedIL('Proxy instruction bound exceeded')
            row, current = instructions[ip], ip
            op, operand, ip = row['opcode'], row['operand'], following[ip]
            try:
                if op.startswith('ldarg.'):
                    stack.append(args[operand['index'] if op.endswith('.s') else int(op[-1])])
                elif op.startswith('ldloca') or op.startswith('ldloc.'):
                    stack.append(locals_[operand['index'] if op.endswith('.s') else int(op[-1])])
                elif op.startswith('stloc.'):
                    locals_[operand['index'] if op.endswith('.s') else int(op[-1])] = stack.pop()
                elif op == 'ldnull':
                    stack.append(None)
                elif op.startswith('ldc.i4'):
                    stack.append(operand if op in ('ldc.i4', 'ldc.i4.s') else
                                 (-1 if op.endswith('.m1') else int(op[-1])))
                elif op == 'ldfld':
                    stack.append(stack.pop().fields[operand['name']])
                elif op == 'ldstr' or op == 'ldftn':
                    stack.append(operand)
                elif op in ('call', 'callvirt', 'newobj'):
                    count = operand['parameters']
                    arguments = stack[-count:] if count else []
                    if count:
                        del stack[-count:]
                    receiver = stack.pop() if operand['instance'] and op != 'newobj' else None
                    if op == 'callvirt' and receiver is None:
                        raise ProxyFailure('null callvirt receiver')
                    value = self.call(operand, receiver, arguments, constructor=op == 'newobj')
                    if op == 'newobj' or operand['returns'] != 'System.Void':
                        stack.append(value)
                elif op in ('isinst', 'castclass'):
                    value = stack.pop()
                    matched = self.is_instance(value, operand['name'])
                    if op == 'castclass' and value is not None and not matched:
                        raise ProxyFailure('invalid cast')
                    stack.append(value if matched else None)
                elif op in ('br', 'br.s'):
                    ip = operand['offset']
                elif op in ('brfalse', 'brfalse.s', 'brtrue', 'brtrue.s'):
                    value = stack.pop()
                    truth = value is not None and value is not False and value != 0
                    if truth == op.startswith('brtrue'):
                        ip = operand['offset']
                elif op in ('ble', 'ble.s'):
                    right, left = stack.pop(), stack.pop()
                    if left <= right:
                        ip = operand['offset']
                elif op == 'add':
                    stack.append(stack.pop() + stack.pop())
                elif op == 'pop':
                    stack.pop()
                elif op in ('leave', 'leave.s'):
                    target = operand['offset']
                    for handler in handlers(current):
                        if handler['kind'] == 'Finally' and not handler['try_start'] <= target < handler['try_end']:
                            self.execute(method, args, locals_, handler['handler_start'], finally_block=True)
                    stack.clear()
                    ip = target
                elif op == 'endfinally' and finally_block:
                    return None
                elif op == 'constrained.':
                    pass  # Proxy enumerators are reference objects, not CLR structs.
                elif op == 'ret':
                    if stack:
                        raise UnsupportedIL('Unexpected return stack')
                    return None
                else:
                    raise UnsupportedIL('Unsupported IL instruction: ' + op)
            except ProxyFailure as error:
                caught = False
                for handler in handlers(current):
                    if handler['kind'] == 'Finally':
                        self.execute(method, args, locals_, handler['handler_start'], finally_block=True)
                    elif handler['kind'] == 'Catch' and handler['catch_type'] == 'System.Exception':
                        self.trace.append({'caught_by_original_il': method['name'], 'offset': current,
                                           'handler': handler['handler_start'], 'exception': type(error).__name__})
                        stack[:] = [error]
                        ip, caught = handler['handler_start'], True
                        break
                    else:
                        raise UnsupportedIL('Unsupported exception handler')
                if not caught:
                    raise
        raise UnsupportedIL('Method fell through')


def exercise(methods):
    cases = []
    def run(name, *, expanded=False, failure=None, fail_call=None, control_tree=False):
        vm = VM(methods, expand=expanded, fail_at=failure, fail_call=fail_call)
        args = [vm.form, vm.form.children] if control_tree else None
        outcome = 'returned'
        try:
            vm.run(name, args)
        except ProxyFailure:
            outcome = 'proxy_failure'
        row = {'method': name, 'expanded': expanded, 'failure_call_index': failure,
               'failure_receiver_and_method': list(fail_call) if fail_call else None, 'outcome': outcome,
               'instruction_steps': vm.steps, 'call_count': vm.calls, 'trace': vm.trace,
               'redraw_running': vm.form.fields['RedrawTimer'].fields.get('running'),
               'checked_radios': [key for key, value in vm.form.fields.items()
                                  if isinstance(value, Node) and value.kind == 'radio'
                                  and value.fields.get('Checked') == 1],
               'panel_count': len(vm.form.fields['_lWidgetPanels']),
               'restore_control_count': len(vm.form.fields['flpWidgetPresetLevels'].children)}
        cases.append(row)
        return vm, row
    for name in ('BeforeChangePpAttributes', 'AfterChangePpAttributes'):
        vm, baseline = run(name)
        expected_count = 8 if name.startswith('Before') else 10
        assert vm.calls == expected_count
        assert baseline['redraw_running'] is (name == 'AfterChangePpAttributes')
        if name == 'BeforeChangePpAttributes':
            assert len(baseline['checked_radios']) == 7
        for index in range(1, expected_count+1):
            _, failed = run(name, failure=index)
            assert failed['outcome'] == 'proxy_failure' and failed['call_count'] == index
            assert failed['redraw_running'] is not True
    vm, row = run('SetUpControls', expanded=True, control_tree=True)
    bound = [event['receiver'] for event in vm.trace if event.get('method', '').endswith('::set_DataBindingObject')]
    assert bound == ['nested-radio', 'outer-combo', 'plain-child-combo'], bound
    vm, row = run('SetUpControls', expanded=True, control_tree=True,
                  fail_call=('outer-combo', 'set_DataBindingObject'))
    assert row['outcome'] == 'returned' and vm.fault_fired
    assert any(event.get('caught_by_original_il') == 'SetUpControls' for event in vm.trace)
    assert any(event.get('receiver') == 'plain-child-combo' and event.get('method', '').endswith('::set_DataBindingObject') for event in vm.trace)
    vm, row = run('SetUpControls', expanded=True, control_tree=True,
                  fail_call=('nested-radio', 'set_DataBindingObject'))
    assert row['outcome'] == 'returned' and vm.fault_fired
    assert any(event.get('caught_by_original_il') == 'SetUpControls' for event in vm.trace)
    assert any(event.get('receiver') == 'outer-combo' and event.get('method', '').endswith('::set_DataBindingObject') for event in vm.trace)
    vm, row = run('ResetControlBinding', expanded=True, control_tree=True)
    assert any(event.get('receiver') == 'basewidget-child-combo' and event.get('method', '').endswith('::SetUpDataBindings') for event in vm.trace)
    vm, row = run('ResetControlBinding', expanded=True, control_tree=True,
                  fail_call=('nested-radio', 'set_DataBindingObject'))
    assert row['outcome'] == 'proxy_failure'
    assert vm.trace[-1]['method'] == 'System.IDisposable::Dispose'
    vm, row = run('PopulateWidgetPanels', expanded=True)
    assert row['panel_count'] == 16
    for receiver, name in (('old-panel1', 'Dispose'), (None, '.ctor')):
        vm, row = run('PopulateWidgetPanels', expanded=True, fail_call=(receiver, name))
        assert row['outcome'] == 'proxy_failure'
        assert row['panel_count'] == (2 if receiver else 0)
        assert not any(event.get('method', '').endswith('::ResumeDrawing') for event in vm.trace)
    vm, row = run('SetupForm', expanded=True)
    assert row['restore_control_count'] == 16
    vm, row = run('SetupForm', expanded=True, fail_call=('PP0', 'add_PropertyChanged'))
    assert row['outcome'] == 'returned' and row['restore_control_count'] == 16
    assert any(event.get('method', '').endswith('::OnFormClosed') for event in vm.trace)
    vm, row = run('AfterChangePpAttributes', expanded=True)
    assert row['redraw_running'] is True and row['restore_control_count'] == 16
    return cases


def capture(edlt_dll, mono_root, output):
    dll, mono, out = Path(edlt_dll).resolve(), Path(mono_root).resolve(), Path(output).absolute()
    if digest(dll) != DLL_SHA256:
        raise ValueError('Requires pinned eDLT.dll')
    for relative, wanted in PINS.items():
        if digest(mono / relative) != wanted:
            raise ValueError('Requires pinned owned runtime: ' + relative)
    source = Path(__file__).with_name('edlt_template_rebind_metadata.cs')
    tracked = [dll, Path(__file__).resolve(), source, *(mono / relative for relative in PINS)]
    before = {str(path): digest(path) for path in tracked}
    out.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith(('CBUS_', 'MONO_', 'DYLD_')) and key not in ('PYTHONPATH', 'PYTHONHOME')}
    cecil = mono / 'lib/mono/gac/Mono.Cecil/0.11.1.0__0738eb9f132ed756/Mono.Cecil.dll'
    env.update(MONO_CFG_DIR=str(mono / 'etc'), MONO_PATH=str(cecil.parent) + os.pathsep + str(mono / 'lib/mono/4.5'), DYLD_FALLBACK_LIBRARY_PATH=str(mono / 'lib'))
    runtime = [str(mono / 'bin/mono-sgen64')]
    commands = [
        ('compile', runtime + [str(mono / 'lib/mono/4.5/mcs.exe'), '-r:' + str(cecil),
            '-r:' + str(mono / 'lib/mono/4.5/System.Web.Extensions.dll'),
            '-out:' + str(out / 'Metadata.exe'), str(source)]),
        ('metadata', runtime + [str(out / 'Metadata.exe'), str(dll)]),
    ]
    report = {'format': 'cbus-edlt-template-rebind-proxy-v1', 'passed': False,
        'scope': 'Pinned original IL interpreted with explicit synthetic proxy calls; metadata reader runs in owned Mono',
        'python_version': sys.version,
        'original_method_bodies_interpreted': False, 'original_methods_executed_by_clr': False,
        'original_form_executed': False, 'model_callbacks_executed': False,
        'control_binding_effects_verified': False, 'rendering_verified': False,
        'network_io_attempted': False, 'persisted': False, 'commands': [], 'inputs_before': before}
    try:
        for name, command in commands:
            command = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', *command]
            result = subprocess.run(command, env=env, capture_output=True, timeout=30)
            (out / (name + '.stdout')).write_bytes(result.stdout)
            (out / (name + '.stderr')).write_bytes(result.stderr)
            report['commands'].append({'stage': name, 'argv': command, 'returncode': result.returncode, 'network_denied': True})
            if result.returncode:
                raise RuntimeError('Managed metadata stage failed: ' + name)
        document = json.loads((out / 'metadata.stdout').read_text())
        if document['assembly_sha256'] != DLL_SHA256 or document['original_methods_executed']:
            raise AssertionError('Wrong extraction source')
        methods = {m['name']: m for m in document['methods']}
        for name, wanted in EXPECTED_ROOTS.items():
            if methods[name]['il_sha256'] != wanted:
                raise AssertionError('Original method IL changed: ' + name)
        report['method_proofs'] = [{key: m[key] for key in ('name', 'token', 'rva', 'il_sha256', 'il_size')}
                                   | {'direct_calls': [row['operand']['signature'] for row in m['instructions']
                                       if row['opcode'] in ('call', 'callvirt', 'newobj')],
                                      'handlers': m['handlers']} for m in methods.values()]
        report['cases'] = exercise(methods)
        report['original_method_bodies_interpreted'] = True
        report['inputs_after'] = {str(path): digest(path) for path in tracked}
        if report['inputs_after'] != before:
            raise AssertionError('Inputs changed')
        report['passed'] = True
    except BaseException as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        report['artifacts'] = {p.name: digest(p) for p in out.iterdir() if p.is_file()}
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def compact_fixture(report):
    """Publish observations and source hashes, never the extracted IL stream."""
    if not report.get('passed'):
        raise ValueError('A completed probe is required')
    mechanical = {'GetEnumerator', 'MoveNext', 'get_Current', 'get_Controls',
                  'get_Count', 'get_Item', 'get_DataBindings'}
    cases = []
    for row in report['cases']:
        record = {key: value for key, value in row.items() if key != 'trace'}
        record['trace_sha256'] = hashlib.sha256(json.dumps(
            row['trace'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        record['callbacks'] = [event for event in row['trace'] if
            event.get('method', '').rsplit('::', 1)[-1] not in mechanical]
        cases.append(record)
    return {'format': 'cbus-edlt-template-rebind-proxy-vectors-v1',
        'scope': report['scope'], 'passed': True,
        'original_method_bodies_interpreted': True, 'original_methods_executed_by_clr': False,
        'original_form_executed': False, 'model_callbacks_executed': False,
        'control_binding_effects_verified': False, 'rendering_verified': False,
        'network_io_attempted': False, 'persisted': False,
        'source_sha256': {Path(path).name: value for path, value in report['inputs_before'].items()},
        'method_proofs': report['method_proofs'], 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edlt-dll', required=True)
    parser.add_argument('--mono-root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--verify-fixture')
    args = parser.parse_args()
    result = capture(args.edlt_dll, args.mono_root, args.output)
    if args.verify_fixture:
        expected = json.loads(Path(args.verify_fixture).read_text())
        verified = compact_fixture(result) == expected
        (Path(args.output) / 'fixture-verification.json').write_text(json.dumps({
            'passed': verified, 'fixture_sha256': digest(args.verify_fixture),
            'compared_cases': len(result['cases'])}, indent=2) + '\n')
        if not verified:
            raise AssertionError('Fresh proxy observations differ from the retained fixture')
    print(json.dumps({'passed': result['passed'], 'cases': len(result['cases']),
                      'original_form_executed': False, 'output': args.output}))
