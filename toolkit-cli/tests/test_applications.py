import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from cbus_toolkit.applications import ApplicationError, NativeTrigger, action_selector, encode_trigger_event, encode_indicator_kill, parse_trigger_event


class Reply:
    def __init__(self, *lines):
        self.lines = lines


class Client:
    def __init__(self, reply=None):
        self.reply = reply or Reply('200 OK.')
        self.commands = []
        self.xml_reply = Reply('343-Begin XML snippet', '347-<NetVar><Level Value="123"><TagName>Evening</TagName></Level></NetVar>', '344 End XML snippet')

    def command(self, command):
        self.commands.append(command)
        if command.startswith('DBGETXML '):
            return self.xml_reply
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class ApplicationTests(unittest.TestCase):
    def test_literal_native_trigger_event_parser_and_correlation(self):
        line = '#e# 20260914-100043.053 702 //TRGA1393/254/202/1 0f5423b0-9251-103f-b8f5-c222a1decd35 [trigger] event action=123 sourceUnit=16 sessionId=cmd713 commandId=56'
        event = parse_trigger_event(line)
        self.assertEqual((event.kind, event.selector, event.source_unit, event.session_id, event.command_id), ('event', 123, 16, 'cmd713', '56'))
        killed = parse_trigger_event(line.replace('event action=123', 'indicatorkill action=-1'))
        self.assertIsNone(killed.selector)
        self.assertIsNone(parse_trigger_event('#e# 20260914-100043.053 702 //TEST/254/202 oid [trigger] loaded application'))
        self.assertIsNone(parse_trigger_event('#e# 20260914-100043.053 761 cmd713 - Command: TRIGGER EVENT'))
        for change in ('event action=256', 'min action=1', 'indicatorkill action=0'):
            with self.assertRaises(ApplicationError):
                parse_trigger_event(line.replace('event action=123', change))

    def test_native_literal_event_and_kill_vectors(self):
        self.assertEqual(encode_trigger_event(1, 123), bytes.fromhex('02017b'))
        self.assertEqual(encode_trigger_event(1, '50%'), bytes.fromhex('02017f'))
        self.assertEqual(encode_indicator_kill(1), bytes.fromhex('0901'))

    def test_selector_forms_and_native_integer_percentage(self):
        for value, expected in ((0, '0'), (255, '255'), ('1%', '2'), ('50%', '127'), ('100%', '255'), ('$7b', '123'), ('0xFF', '255'), ('0b11', '3'), ('Evening', 'Evening')):
            self.assertEqual(action_selector(value), expected)
        for value in (True, -1, 256, '256', '-1', '101%', '-1%', '1.5%', '0xGG', '0b2', '', 'A\nNOOP'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                action_selector(value)
        with self.assertRaises(ApplicationError):
            encode_trigger_event(1, 'Evening')

    def test_native_commands_and_explicit_force(self):
        client = Client()
        trigger = NativeTrigger(client)
        trigger.event('//TEST/254/202/1', '50%')
        trigger.event('//TEST/254/202/1', 'Evening', force=True)
        trigger.indicator_kill('//TEST/254/202/1')
        self.assertEqual(client.commands, ['TRIGGER EVENT //TEST/254/202/1 127', 'DBGETXML //TEST/254/202/1', 'TRIGGER EVENT //TEST/254/202/1 123 FORCE', 'TRIGGER INDICATORKILL //TEST/254/202/1'])
        with self.assertRaises(ApplicationError):
            trigger.event('//TEST/254/202/1', 1, force='true')
        self.assertEqual(len(client.commands), 4)

    def test_level_tag_resolution_supports_spaces_and_rejects_ambiguity_before_event(self):
        client = Client()
        trigger = NativeTrigger(client)
        client.xml_reply = Reply('347-<Group><Level Value="7"><TagName>Evening scene</TagName></Level></Group>')
        trigger.event('//TEST/254/202/1', 'Evening scene')
        self.assertEqual(client.commands[-1], 'TRIGGER EVENT //TEST/254/202/1 7')
        for xml in ('<Group/>', '<Group><Level Value="1"><TagName>Same</TagName></Level><Level Value="2"><TagName>Same</TagName></Level></Group>', '<Group><Level><TagName>Same</TagName></Level></Group>', '<Group><Level Value="999"><TagName>Same</TagName></Level></Group>', '<!DOCTYPE Group><Group/>'):
            client.commands.clear()
            client.xml_reply = Reply('347-' + xml)
            with self.subTest(xml=xml), self.assertRaises(ApplicationError):
                trigger.event('//TEST/254/202/1', 'Same')
            self.assertEqual(client.commands, ['DBGETXML //TEST/254/202/1'])

    def test_cached_attribute_reads_preserve_native_meaning(self):
        client = Client(Reply('300-//TEST/254/202/1: EventLevel=5', '300-//TEST/254/202/1: Name=Scene', '300 //TEST/254/202/1: State=ok'))
        result = NativeTrigger(client).get('//TEST/254/202/1')
        self.assertEqual(result['objects'], {'//TEST/254/202/1': {'EventLevel': '5', 'Name': 'Scene', 'State': 'ok'}})
        self.assertTrue(result['cached'])
        self.assertNotIn('selector', result)
        client.reply = Reply('300 //TEST/254/202/1: State=ok')
        NativeTrigger(client).state('//TEST/254/202/1')
        self.assertEqual(client.commands[-1], 'GET //TEST/254/202/1 State')

    def test_group_lists_and_malformed_responses(self):
        client = Client(Reply('300 //TEST/254/202: Groups=0,1,255'))
        result = NativeTrigger(client).groups('//TEST/254/202')
        self.assertEqual(result['groups'], {'//TEST/254/202': [0, 1, 255]})
        for text in ('1,1', '256', '-1', 'one'):
            client.reply = Reply('300 //TEST/254/202: Groups=' + text)
            with self.assertRaises(RuntimeError):
                NativeTrigger(client).groups('//TEST/254/202')
        for lines in ((), ('200 OK.',), ('300 //TEST/254/202/1: State=ok', '300 //TEST/254/202/1: state=closed')):
            client.reply = Reply(*lines)
            with self.assertRaises(RuntimeError):
                NativeTrigger(client).get('//TEST/254/202/1')

    def test_failures_are_not_retried_and_targets_cannot_inject(self):
        client = Client(RuntimeError('network closed'))
        with self.assertRaises(RuntimeError):
            NativeTrigger(client).event('//TEST/254/202/1', 1)
        self.assertEqual(len(client.commands), 1)
        with self.assertRaises(ValueError):
            NativeTrigger(client).indicator_kill('//TEST/254/202/1\nNOOP')
        self.assertEqual(len(client.commands), 1)


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST'), 'Set CBUS_CGATE_TEST_HOST for disposable native Trigger Control acceptance')
class NativeApplicationTests(unittest.TestCase):
    def test_native_trigger_events_selector_tags_kill_and_persistence(self):
        from cbus_toolkit.cgate import CGateClient, CGateError
        from cbus_toolkit.simulator import PCISimulator
        project = 'TRG' + uuid4().hex[:5].upper()
        network = f'//{project}/254'
        group = network + '/202/1'
        report = {'project': project, 'commands': [], 'scope': 'Native queued Trigger Control to independent synthetic receiver; no physical scene execution claim'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            # Avoid C-Gate's documented immediate-confirmation sender race.
            simulator = PCISimulator(profile='synthetic', state_path=path, response_delay=0.01)
            with simulator.running('0.0.0.0', 0) as (_, port), CGateClient(os.environ['CBUS_CGATE_TEST_HOST'], port=int(os.environ.get('CBUS_CGATE_TEST_PORT', '20023')), timeout=30) as client:
                report['greeting'] = client.greeting
                created = False
                def command(text):
                    response = client.command(text)
                    report['commands'].append({'command': text, 'lines': list(response.lines), 'command_id': str(client._sequence)})
                    return response
                class RecordingClient:
                    def command(self, text):
                        return command(text)
                trigger = NativeTrigger(RecordingClient())
                def eventually(predicate):
                    deadline = time.monotonic() + 5
                    while not predicate() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(predicate(), simulator.triggers.snapshot())
                try:
                    command('PROJECT NEW ' + project)
                    created = True
                    command('PROJECT USE ' + project)
                    command('PROJECT SAVE ' + project)
                    command(f'DBCREATENET 254 Trigger Cni {os.environ.get("CBUS_CGATE_SIMULATOR_HOST", "host.docker.internal")}:{port}')
                    command(f'DBADDSAFE {network} Application 202 Trigger')
                    command(f'DBADDSAFE {network}/202 NetVar 1 Scene')
                    level = command(f'DBADDSAFE {group} Level 123 Evening')
                    level_oid = level.lines[-1].split('OID=', 1)[1]
                    command(f'DBSET !{level_oid}/Value 123')
                    command('PROJECT SAVE ' + project)
                    command('NET LOAD DB ' + project)
                    command('EVENT e9s0c0')
                    command('NET OPEN ' + network)
                    deadline = time.monotonic() + 20
                    while True:
                        state = command('GET ' + network + ' state')
                        if any('state=ok' in line for line in state.lines):
                            break
                        self.assertLess(time.monotonic(), deadline, state.lines)
                        time.sleep(0.1)
                    native_events, event_lines, expected_command_ids = [], [], []
                    for index, (selector, expected_selector) in enumerate(zip((0, 255, '50%', 'Evening', 'Evening'), (0, 255, 127, 123, 123)), 1):
                        trigger.event(group, selector, force=selector == 'Evening')
                        command_id = str(client._sequence)
                        expected_command_ids.append(command_id)
                        # Native200 and simulator mutation precede completion.
                        # The exact702 follows removal from C-Gate's active
                        # sender cache, so an identical next EVENT is distinct.
                        deadline = time.monotonic() + 5
                        previous_timeout = client.timeout
                        try:
                            while not any(event.command_id == command_id and event.source_unit == 16 for event in native_events):
                                remaining = deadline - time.monotonic()
                                self.assertGreater(remaining, 0, 'Timed out waiting for the correlated Trigger event command ' + command_id)
                                client.timeout = min(previous_timeout, remaining)
                                line = client.read_event()
                                event_lines.append(line)
                                event = parse_trigger_event(line)
                                if event is not None and event.address == group:
                                    native_events.append(event)
                        finally:
                            client.timeout = previous_timeout
                        matched = [event for event in native_events if event.command_id == command_id and event.source_unit == 16]
                        self.assertEqual(len(matched), 1)
                        self.assertEqual(matched[0].selector, expected_selector)
                        eventually(lambda: simulator.triggers.groups.get(1, {}).get('event_count') == index)
                    eventually(lambda: simulator.triggers.groups.get(1, {}).get('event_count') == 5)
                    self.assertEqual(simulator.triggers.groups[1]['selector'], 123)
                    trigger.indicator_kill(group)
                    expected_command_ids.append(str(client._sequence))
                    eventually(lambda: simulator.triggers.groups[1]['kill_count'] == 1)
                    self.assertEqual(simulator.triggers.groups[1], {'selector': 123, 'indicator_active': False, 'event_count': 5, 'kill_count': 1})
                    self.assertEqual([event['selector'] for event in simulator.triggers.events], [0, 255, 127, 123, 123, None])
                    attributes = trigger.get(group)
                    self.assertEqual(set(attributes['objects'][group]), {'EventLevel', 'Name', 'State'})
                    self.assertEqual(trigger.state(group)['objects'][group], {'State': 'ok'})
                    self.assertEqual(trigger.groups(network + '/202')['groups'], {network + '/202': [1]})
                    # PCI receipt precedes C-Gate's asynchronous702 notification;
                    # cached GET replies do not establish event delivery.
                    deadline = time.monotonic() + 5
                    previous_timeout = client.timeout
                    try:
                        while not native_events or native_events[-1].kind != 'indicatorkill' or native_events[-1].command_id != expected_command_ids[-1] or native_events[-1].source_unit != 16:
                            remaining = deadline - time.monotonic()
                            self.assertGreater(remaining, 0, 'Timed out waiting for the correlated Trigger indicator-kill event')
                            client.timeout = min(previous_timeout, remaining)
                            line = client.read_event()
                            event_lines.append(line)
                            event = parse_trigger_event(line)
                            if event is not None and event.address == group:
                                native_events.append(event)
                    finally:
                        client.timeout = previous_timeout
                    self.assertEqual([event.selector for event in native_events], [0, 255, 127, 123, 123, None])
                    self.assertTrue(all(event.source_unit == 16 and event.session_id and event.command_id for event in native_events))
                    self.assertEqual([event.command_id for event in native_events], expected_command_ids)
                    self.assertEqual(len({event.session_id for event in native_events}), 1)
                    with self.assertRaises(CGateError) as captured:
                        trigger.get(group, 'Level')
                    self.assertEqual(captured.exception.response.code, 402)
                    report['unsupported_native_level_get'] = list(captured.exception.response.lines)
                    reloaded = PCISimulator(profile='synthetic', state_path=path)
                    self.assertEqual(reloaded.triggers.snapshot(), simulator.triggers.snapshot())
                    self.assertFalse([item for item in simulator.wire_log if 'reason' in item])
                    report.update(passed=True, persisted=True, trigger_state=simulator.triggers.snapshot(), native_events=event_lines + list(client.events), wire=list(simulator.wire_log), response_delay_seconds=0.01, event_collection_deadline_seconds=5, per_command_event_barrier=True, expected_event_command_ids=expected_command_ids)
                finally:
                    if created:
                        for text in ('NET CLOSE ' + network, 'PROJECT CLOSE ' + project, 'PROJECT DELETE ' + project):
                            if not client.connected:
                                client.connect()
                            command(text)
            if os.environ.get('CBUS_TRIGGER_REPORT'):
                output = Path(os.environ['CBUS_TRIGGER_REPORT'])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
