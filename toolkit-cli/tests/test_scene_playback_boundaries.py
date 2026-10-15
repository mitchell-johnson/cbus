"""P7.02 slice: scene-file playback command boundaries without I/O.

Pins SceneExecutor's ON/OFF-versus-RAMP selection and its stop-without-replay
contract over a recording fake client: only a zero-duration 0/255 level uses
the ON/OFF verbs; every other action uses RAMP; a rejected command raises
SceneExecutionError carrying the completed prefix; record() samples cached
levels without mutating its input. No server, scene-set, or device involved.
"""
import unittest

from cbus_toolkit.cgate import CGateResponse
from cbus_toolkit.scenes import SceneAction, SceneError, SceneFile, SceneExecutionError, SceneExecutor


def ok():
    return CGateResponse(("200 OK.",), "200 OK.", 200)


class FakeClient:
    def __init__(self, levels=None, refuse=()):
        self.levels = dict(levels or {})
        self.refuse = set(refuse)
        self.commands = []

    def command(self, command):
        self.commands.append(command)
        if command in self.refuse:
            return CGateResponse(("401 rejected",), "401 rejected", 401)
        if command.startswith("GET "):
            address = command[4:].rsplit(" ", 1)[0]
            if address not in self.levels:
                return CGateResponse(("300 no cached levels reported",),
                                     "300 no cached levels reported", 200)
            return CGateResponse((f"300 {address}: level={self.levels[address]}",),
                                 f"300 {address}: level={self.levels[address]}", 200)
        return ok()


class PlaybackBoundaryTests(unittest.TestCase):
    def play(self, actions, **client_options):
        client = FakeClient(**client_options)
        scene = SceneFile(tuple(actions))
        return client, SceneExecutor(client).play(scene)

    def test_on_off_used_only_for_instant_extremes(self):
        client, _ = self.play([SceneAction("254/56/1", 0), SceneAction("254/56/2", 255)])
        self.assertEqual(client.commands, ["LIGHTING OFF 254/56/1", "LIGHTING ON 254/56/2"])

    def test_ramp_used_for_everything_else(self):
        actions = [SceneAction("254/56/1", 0, 4), SceneAction("254/56/2", 255, 4),
                   SceneAction("254/56/3", 128), SceneAction("254/56/4", 1)]
        client, playback = self.play(actions)
        self.assertEqual(client.commands, ["LIGHTING RAMP 254/56/1 0 4", "LIGHTING RAMP 254/56/2 255 4",
                                           "LIGHTING RAMP 254/56/3 128 0", "LIGHTING RAMP 254/56/4 1 0"])
        self.assertTrue(playback.queued)
        self.assertFalse(playback.device_verified)
        self.assertEqual(len(playback.responses), 4)

    def test_rejected_command_stops_without_replay(self):
        client = FakeClient(refuse={"LIGHTING RAMP 254/56/2 10 0"})
        scene = SceneFile((SceneAction("254/56/1", 10), SceneAction("254/56/2", 10),
                           SceneAction("254/56/3", 10)))
        with self.assertRaises(SceneExecutionError) as caught:
            SceneExecutor(client).play(scene)
        self.assertEqual(caught.exception.index, 1)
        self.assertEqual(len(caught.exception.completed), 1)
        # The failed and later actions were never accepted; nothing replays them.
        self.assertEqual(client.commands, ["LIGHTING RAMP 254/56/1 10 0", "LIGHTING RAMP 254/56/2 10 0"])
        self.assertEqual(caught.exception.details["failed_action_index"], 1)
        self.assertEqual(caught.exception.details["completed_count"], 1)

    def test_record_samples_levels_without_mutating_input(self):
        scene = SceneFile((SceneAction("254/56/1", 0), SceneAction("254/56/2", 0, 7)),
                          play_trigger="254/56/9")
        client = FakeClient(levels={"254/56/1": 200, "254/56/2": 33})
        recorded = SceneExecutor(client).record(scene)
        self.assertEqual(recorded.actions, (SceneAction("254/56/1", 200), SceneAction("254/56/2", 33)))
        self.assertEqual(recorded.play_trigger, "254/56/9")
        self.assertEqual(scene.actions, (SceneAction("254/56/1", 0), SceneAction("254/56/2", 0, 7)))
        self.assertEqual(client.commands, ["GET 254/56/1 level", "GET 254/56/2 level"])

    def test_record_rejects_ambiguous_or_missing_levels(self):
        class BadClient(FakeClient):
            def command(self, command):
                self.commands.append(command)
                return CGateResponse(("300 //x: level=1", "300 //y: level=2"),
                                     "300 //y: level=2", 200)

        scene = SceneFile((SceneAction("254/56/1", 0),))
        with self.assertRaises(SceneError):
            SceneExecutor(BadClient()).record(scene)
        with self.assertRaises(SceneError):
            SceneExecutor(FakeClient(levels={})).record(scene)


if __name__ == "__main__":
    unittest.main()
