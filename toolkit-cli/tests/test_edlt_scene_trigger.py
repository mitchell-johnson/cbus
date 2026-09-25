"""Retained eDLT scene trigger selection and one-shot C-Gate execution."""
from dataclasses import replace
import unittest

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_scene_manager import EdltSceneManager
from cbus_toolkit.edlt_scene_trigger import NativeEdltSceneTrigger
from tests.test_edlt_scene_live import Client, reply, vectors
from tests.test_edlt_scene_manager import cache, fixture, Session, op


class SceneTriggerTests(unittest.TestCase):
    def setUp(self):
        self.spec = fixture()
        self.manager = EdltSceneManager(self.spec)
        session = Session(self.spec)
        source = {**session.current,
                  **{key: value for key, value in vectors()['input'].items()
                     if key in self.spec.parameters}}
        self.state = self.manager.load(source, metadata=cache())

    def trigger(self, client):
        return NativeEdltSceneTrigger(
            self.manager, client, network='//OWNED/254')

    def test_plan_uses_exact_retained_trigger_binding_without_io(self):
        client = Client()
        sender = self.trigger(client)
        first = sender.plan(self.state, scene=1)
        second = sender.plan(self.state, scene=2, force=True)

        self.assertEqual(first.command,
                         'TRIGGER EVENT //OWNED/254/202/42 1')
        self.assertEqual(second.command,
                         'TRIGGER EVENT //OWNED/254/202/42 2 FORCE')
        self.assertEqual(client.commands, [])
        self.assertEqual(first.as_dict(), {
            'format': 'cbus-edlt-scene-trigger-plan-v1',
            'profile': {'unit_type': 'KEYGL5',
                        'catalog_number': '5055EDL',
                        'firmware': '5.5.00'},
            'network': '//OWNED/254', 'scene': 1,
            'trigger_application': 202, 'trigger_group': 42,
            'action_selector': 1, 'force': False,
            'address': '//OWNED/254/202/42',
            'command': 'TRIGGER EVENT //OWNED/254/202/42 1',
            'binding_source': 'retained KEYGL5 scene table',
            'metadata_created': False,
            'source_snapshot_freshness_verified': False,
            'metadata_cache_freshness_verified': False,
            'physical_binding_readback': False,
            'network_io_performed': False,
            'saved': False, 'pp_writes': 0,
        })

    def test_one_accepted_command_has_bounded_evidence_and_no_retry(self):
        client = Client(reply('200 OK'))
        result = self.trigger(client).trigger(self.state, scene=1, force=True)

        self.assertEqual(client.commands,
                         ['TRIGGER EVENT //OWNED/254/202/42 1 FORCE'])
        self.assertTrue(result.complete)
        self.assertEqual(result.status, 'accepted')
        evidence = result.as_dict()
        self.assertTrue(evidence['native_command_accepted'])
        self.assertFalse(evidence['physical_scene_execution_verified'])
        self.assertFalse(evidence['device_verified'])
        self.assertFalse(evidence['source_snapshot_freshness_verified'])
        self.assertFalse(evidence['physical_binding_readback'])
        self.assertEqual(evidence['attempted_count'], 1)
        self.assertEqual(evidence['automatic_retries'], 0)
        self.assertEqual(evidence['pp_writes'], 0)
        self.assertFalse(evidence['saved'])

    def test_missing_or_stale_binding_and_forged_state_fail_before_io(self):
        client = Client()
        sender = self.trigger(client)
        missing_group = self.manager.edit(
            self.state, operations=[op('set-trigger', group=255)]).state
        missing_action = self.manager.edit(
            self.state, operations=[op('set-action', action=99)]).state
        incomplete = replace(self.state, complete=False)

        for state, message in ((missing_group, 'trigger group'),
                               (missing_action, 'action selector'),
                               (incomplete, 'review-only')):
            with self.subTest(message=message):
                with self.assertRaisesRegex(EdltError, message):
                    sender.plan(state, scene=1)
        other = EdltSceneManager(self.spec)
        with self.assertRaisesRegex(EdltError, 'issued'):
            NativeEdltSceneTrigger(
                other, client, network='//OWNED/254').plan(
                    self.state, scene=1)
        self.assertEqual(client.commands, [])

    def test_rejection_malformed_reply_transport_and_disconnect_are_distinct(self):
        cases = (
            (CGateError(reply('401 Owned rejection')), 'rejected', False, False),
            (reply('202 Done'), 'response-error', False, True),
            (OSError('lost acknowledgement'), 'transport-error', False, True),
        )
        for response, status, complete, uncertain in cases:
            with self.subTest(status=status):
                client = Client(response)
                sender = self.trigger(client)
                result = sender.trigger(self.state, scene=1)
                self.assertEqual(result.status, status)
                self.assertEqual(result.complete, complete)
                self.assertEqual(result.outcome_uncertain, uncertain)
                self.assertEqual(len(client.commands), 1)
                self.assertEqual(sender.last_evidence, result.as_dict())
                self.assertEqual(result.as_dict()['automatic_retries'], 0)

        client = Client(reply('200 OK'))
        client.connected = False
        result = self.trigger(client).trigger(self.state, scene=1)
        self.assertEqual(result.status, 'not-connected')
        self.assertFalse(result.outcome_uncertain)
        self.assertEqual(client.commands, [])

    def test_preflight_bounds_are_strict(self):
        client = Client()
        for network in ('OWNED/254', '//OWNED/0254', '//OWNED/256',
                        '//TOOLONG12/254', '//OWNED/254\nTRIGGER'):
            with self.subTest(network=network):
                with self.assertRaises(EdltError):
                    NativeEdltSceneTrigger(
                        self.manager, client, network=network)
        sender = self.trigger(client)
        for scene in (0, 9, True):
            with self.subTest(scene=scene):
                with self.assertRaises(EdltError):
                    sender.plan(self.state, scene=scene)
        with self.assertRaises(EdltError):
            sender.plan(self.state, scene=1, force=1)
        self.assertEqual(client.commands, [])

    def test_actual_tagged_socket_sends_one_exact_trigger_event(self):
        from cbus_toolkit.cgate import CGateClient
        from tests.test_cgate import peer

        with peer([[b'[1] 200 OK\r\n']]) as (address, commands):
            with CGateClient(*address, timeout=1) as client:
                result = NativeEdltSceneTrigger(
                    self.manager, client, network='//OWNED/254').trigger(
                        self.state, scene=2, force=True)
        self.assertTrue(result.complete)
        self.assertEqual(commands, [
            b'[1] TRIGGER EVENT //OWNED/254/202/42 2 FORCE\r\n'])
