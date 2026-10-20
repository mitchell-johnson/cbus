"""Wave 13 narrow offline pin for P7.02 (C-Gate filesystem scenes).

Pins pure-offline SceneFile edges in scenes.py not covered by test_scenes.py
or test_scene_playback_boundaries.py: empty/comment-only parse round-trips,
canonical emission order (comments, play, record, set lines each carrying
explicit ramp seconds), trigger comment-marker rejection at construction, and
with_action/without_action strictness (typed actions only, bool indexes
rejected, append-at-end preserves metadata). No server, scene-set, device,
or native service involved.
"""
from __future__ import annotations

import unittest

from cbus_toolkit.scenes import SceneAction, SceneError, SceneFile


class EmptyFileWave13Tests(unittest.TestCase):
    def test_empty_text_parses_to_empty_scene_with_empty_text(self):
        scene = SceneFile.parse('')
        self.assertEqual(scene.actions, ())
        self.assertIsNone(scene.play_trigger)
        self.assertIsNone(scene.record_trigger)
        self.assertEqual(scene.comments, ())
        self.assertEqual(scene.to_text(), '')
        self.assertEqual(scene.as_dict(), {
            'format': 'cbus-native-scene-file-v1', 'play_trigger': None,
            'record_trigger': None, 'comments': [], 'actions': []})

    def test_comment_only_file_preserves_comments_without_actions(self):
        scene = SceneFile.parse('# keep\n# dim\n')
        self.assertEqual(scene.actions, ())
        self.assertIsNone(scene.play_trigger)
        self.assertEqual(scene.comments, ('# keep', '# dim'))
        self.assertEqual(scene.to_text(), '# keep\n# dim\n')


class CanonicalEmissionWave13Tests(unittest.TestCase):
    def test_generated_text_orders_comments_play_record_sets(self):
        scene = SceneFile(
            (SceneAction('254/56/1', 0), SceneAction('254/56/2', 127, 4)),
            play_trigger='254/56/27', record_trigger='254/56/33',
            comments=('# keep',))
        self.assertEqual(scene.to_text(), '# keep\nplay 254/56/27\nrecord 254/56/33\n'
                                          'set 254/56/1 0 0\nset 254/56/2 127 4\n')
        self.assertEqual(SceneFile.parse(scene.to_text()), scene)
        self.assertEqual(scene.as_dict()['actions'],
                         [{'address': '254/56/1', 'level': 0, 'ramp_seconds': 0},
                          {'address': '254/56/2', 'level': 127, 'ramp_seconds': 4}])

    def test_trigger_addresses_reject_comment_marker_at_construction(self):
        with self.assertRaisesRegex(SceneError, 'comment marker'):
            SceneFile(play_trigger='254/56/27#x')
        with self.assertRaisesRegex(SceneError, 'comment marker'):
            SceneFile(record_trigger='254/56/33#x')


class EditStrictnessWave13Tests(unittest.TestCase):
    def test_untyped_action_and_bool_index_rejected(self):
        base = SceneFile((SceneAction('a', 1),))
        with self.assertRaisesRegex(SceneError, 'typed SceneAction'):
            base.with_action(0, 'set a 2')
        with self.assertRaises(SceneError):
            base.with_action(True, SceneAction('b', 2))
        with self.assertRaises(SceneError):
            base.without_action(True)

    def test_append_at_end_preserves_metadata_without_mutating_input(self):
        base = SceneFile((SceneAction('a', 1),), play_trigger='p', comments=('# c',))
        edited = (base.with_action(1, SceneAction('b', 2, 3)).without_action(0))
        self.assertEqual(edited.actions, (SceneAction('b', 2, 3),))
        self.assertEqual(edited.play_trigger, 'p')
        self.assertEqual(edited.comments, ('# c',))
        self.assertEqual(base.actions, (SceneAction('a', 1),))
        appended = SceneFile().with_action(0, SceneAction('a', 1))
        self.assertEqual(appended.actions, (SceneAction('a', 1),))


if __name__ == '__main__':
    unittest.main()
