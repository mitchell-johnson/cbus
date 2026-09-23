"""Literal scene grammar and response fixtures, plus explicit native acceptance."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit.cgate import CGateError, CGateResponse
from cbus_toolkit.scenes import (MAX_ACTIONS, MAX_FILE_BYTES, NativeScenes,
                                SceneAction, SceneError, SceneExecutionError,
                                SceneExecutor, SceneFile)


def reply(line='200 OK'):
    return CGateResponse((line,), line, int(line[:3]))


class ScriptClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.commands = []

    def command(self, command):
        self.commands.append(command)
        response = self.responses.pop(0) if self.responses else reply()
        if isinstance(response, Exception):
            raise response
        return response


class SceneFileTest(unittest.TestCase):
    def test_literal_grammar_preserves_untouched_text(self):
        text = '# scene: demo\r\nPLAY //TEST/254/56/27\r\nrecord //TEST/254/56/33\r\n\r\nSET //TEST/254/56/12 255\r\nset //TEST/254/56/24 127 4 # dim\r\nset //TEST/254/56/25 0 0\r\n'
        scene = SceneFile.parse(text)
        self.assertEqual(scene.actions, (SceneAction('//TEST/254/56/12', 255), SceneAction('//TEST/254/56/24', 127, 4), SceneAction('//TEST/254/56/25', 0)))
        self.assertEqual(scene.play_trigger, '//TEST/254/56/27')
        self.assertEqual(scene.record_trigger, '//TEST/254/56/33')
        self.assertEqual(scene.to_text(), text)

    def test_duplicate_triggers_follow_native_last_value(self):
        scene = SceneFile.parse('play 254/56/12\nplay 254/56/24\nrecord 254/56/25\nrecord 254/56/27\n')
        self.assertEqual((scene.play_trigger, scene.record_trigger), ('254/56/24', '254/56/27'))

    def test_edit_append_remove_and_canonical_roundtrip(self):
        original = SceneFile.parse('# keep\nset 254/56/12 0\n')
        edited = original.with_action(0, SceneAction('254/56/12', 255)).with_action(1, SceneAction('254/56/24', 128, 8))
        self.assertEqual(edited.to_text(), '# keep\nset 254/56/12 255 0\nset 254/56/24 128 8\n')
        self.assertEqual(SceneFile.parse(edited.to_text()), edited)
        self.assertEqual(edited.without_action(0).actions, (SceneAction('254/56/24', 128, 8),))
        self.assertEqual(original.actions[0].level, 0)

    def test_rejects_malformed_and_out_of_range_actions(self):
        for text in ('set x 256', 'set x -1', 'set x 1 -1', 'set x 1 2147483648', 'set x 1_0', 'set x 0xFF', 'set x 1 2 extra', 'set x', 'play', 'unknown x 1'):
            with self.subTest(text=text), self.assertRaisesRegex(SceneError, 'Scene line 1'):
                SceneFile.parse(text)
        for arguments in ((1, 0), ('x y', 0), ('x#y', 0), ('x\nOFF y', 0), ('x', True), ('x', 1.5), ('x', 1, False)):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                SceneAction(*arguments)

    def test_limits_are_enforced(self):
        with self.assertRaises(SceneError):
            SceneFile.parse('#' + 'x' * MAX_FILE_BYTES)
        with self.assertRaises(SceneError):
            SceneFile((SceneAction('x', 0),) * (MAX_ACTIONS + 1))
        for index in (-1, 2, True, 1.5):
            with self.assertRaises(SceneError):
                SceneFile((SceneAction('x', 0),)).with_action(index, SceneAction('y', 0))
        with self.assertRaises(SceneError):
            SceneFile().without_action(0)
        with self.assertRaises(SceneError):
            SceneFile(comments=('# comment\nset x 255',))

    def test_save_exclusive_and_atomic_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scene'
            SceneFile((SceneAction('254/56/12', 0),)).save(path)
            before = path.read_bytes()
            scene = SceneFile((SceneAction('254/56/12', 255),))
            with self.assertRaises(SceneError):
                scene.save(path)
            self.assertEqual(path.read_bytes(), before)
            with patch('cbus_toolkit.scenes.os.replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    scene.save(path, overwrite=True)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            scene.save(path, overwrite=True)
            self.assertEqual(SceneFile.load(path), scene)

    def test_load_rejects_oversize_or_invalid_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scene'
            path.write_bytes(b'\xff')
            with self.assertRaisesRegex(SceneError, 'valid utf-8'):
                SceneFile.load(path)
            path.write_bytes(b'#' * (MAX_FILE_BYTES + 1))
            with self.assertRaisesRegex(SceneError, '1 MiB'):
                SceneFile.load(path)


class SceneExecutorTest(unittest.TestCase):
    def test_play_uses_native_off_on_and_ramp_in_order(self):
        client = ScriptClient()
        scene = SceneFile.parse('play 254/56/27\nrecord 254/56/33\nset 254/56/12 255\nset 254/56/24 127 4\nset 254/56/25 0\nset 254/56/12 255 4\n')
        result = SceneExecutor(client).play(scene)
        self.assertEqual(client.commands, ['LIGHTING ON 254/56/12', 'LIGHTING RAMP 254/56/24 127 4', 'LIGHTING OFF 254/56/25', 'LIGHTING RAMP 254/56/12 255 4'])
        self.assertEqual(len(result.responses), 4)
        self.assertTrue(result.queued)
        self.assertFalse(result.device_verified)

    def test_play_stops_after_error_without_retry_or_later_actions(self):
        error = CGateError(reply('401 Bad object/device ID'))
        client = ScriptClient(reply(), error)
        scene = SceneFile.parse('set 254/56/12 255\nset missing 127\nset 254/56/25 255\n')
        with self.assertRaises(SceneExecutionError) as caught:
            SceneExecutor(client).play(scene)
        self.assertEqual(caught.exception.index, 1)
        self.assertEqual(len(caught.exception.completed), 1)
        self.assertIs(caught.exception.cause, error)
        self.assertEqual(len(client.commands), 2)

    def test_pending_or_unexpected_reply_is_not_success(self):
        for code in (202, 300, 600):
            with self.subTest(code=code), self.assertRaises(SceneExecutionError):
                SceneExecutor(ScriptClient(reply(f'{code} pending'))).play(SceneFile((SceneAction('254/56/12', 255),)))

    def test_transport_error_keeps_partial_playback_details(self):
        client = ScriptClient(reply(), OSError('connection reset'))
        scene = SceneFile.parse('set x 0\nset y 255\nset z 127\n')
        with self.assertRaises(SceneExecutionError) as caught:
            SceneExecutor(client).play(scene)
        self.assertEqual(caught.exception.index, 1)
        self.assertEqual(len(caught.exception.completed), 1)
        self.assertIsInstance(caught.exception.cause, OSError)
        self.assertEqual(client.commands, ['LIGHTING OFF x', 'LIGHTING ON y'])

    def test_record_reads_all_before_returning_immutable_replacement(self):
        scene = SceneFile.parse('# preserved\nplay 254/56/27\nset 254/56/12 1 4\nset 254/56/24 2 8\n')
        client = ScriptClient(reply('300 //TEST/254/56/12: level=255'), reply('300 //TEST/254/56/24: level=127'))
        result = SceneExecutor(client).record(scene)
        self.assertEqual(client.commands, ['GET 254/56/12 level', 'GET 254/56/24 level'])
        self.assertEqual(result.actions, (SceneAction('254/56/12', 255), SceneAction('254/56/24', 127)))
        self.assertEqual(result.comments, scene.comments)
        self.assertEqual(result.play_trigger, scene.play_trigger)
        self.assertEqual(scene.actions[0].level, 1)

    def test_failed_record_does_not_modify_input_or_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'scene'
            scene = SceneFile.parse('set 254/56/12 1\nset 254/56/24 2\n')
            scene.save(path)
            before = path.read_bytes()
            client = ScriptClient(reply('300 //TEST/254/56/12: level=255'), RuntimeError('timeout: outcome unknown'))
            with self.assertRaises(RuntimeError):
                SceneExecutor(client).record(scene)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(scene.actions[0].level, 1)

    def test_record_rejects_missing_ambiguous_or_invalid_levels(self):
        ambiguous = CGateResponse(('300-x: level=1', '300 y: level=2'), '300 y: level=2', 300)
        for response in (reply('300 x: state=ok'), reply('300 x: level=256'), reply('300 x: level=-1'), ambiguous):
            with self.subTest(response=response), self.assertRaises(SceneError):
                SceneExecutor(ScriptClient(response)).record(SceneFile((SceneAction('*', 1),)))

    def test_native_wrappers_preserve_errors_and_reject_command_injection(self):
        client = ScriptClient()
        scenes = NativeScenes(client)
        scenes.play('CLI_SCENE', 'evening')
        scenes.record('CLI_SCENE', 'evening')
        self.assertEqual(client.commands, ['SCENE PLAY CLI_SCENE evening', 'SCENE RECORD CLI_SCENE evening'])
        for scene_set, scene in (('set x', 'name'), ('set', 'name\nLIGHTING ON *'), ('', 'name')):
            with self.assertRaises(ValueError):
                scenes.play(scene_set, scene)
        error = CGateError(reply('401 Bad object/device ID'))
        with self.assertRaises(CGateError) as caught:
            NativeScenes(ScriptClient(error)).play('CLI_SCENE', 'evening')
        self.assertIs(caught.exception, error)


@unittest.skipUnless(os.environ.get('CBUS_SCENE_NATIVE') == '1', 'Set CBUS_SCENE_NATIVE=1 for the owned native scene oracle')
class SceneNativeTest(unittest.TestCase):
    def test_native_parser_and_python_execution_against_independent_peer(self):
        research = Path(__file__).resolve().parents[1] / 'research'
        sys.path.insert(0, str(research))
        try:
            from verify_scenes import verify
            report = verify(port=int(os.environ.get('CBUS_SCENE_PORT', '20024')),
                            report_path=os.environ.get('CBUS_SCENE_REPORT'))
        finally:
            sys.path.remove(str(research))
        self.assertTrue(report['passed'], report.get('error', report['checks']))
        self.assertEqual(report['wire_rejections'], [])
        # This known native failure remains separately visible; the Python
        # workflow's pass cannot turn the native SCENE command into a pass.
        self.assertFalse(report['native_scene_commands']['passed'])
        self.assertEqual([row['code'] for row in report['native_scene_commands']['results']], [401, 401])


if __name__ == '__main__':
    unittest.main()
