"""Ordered CLI selections preserve intermediate state and reject bad input."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import edlt_control_cli
from cbus_toolkit.edlt_applications import EdltApplications
from tests.test_edlt_applications import cache_for
from tests.test_edlt_lifecycle import fixture, Session


class OrderedControlOptionsTests(unittest.TestCase):
    def test_application_swaps_keep_user_order_and_no_implicit_release(self):
        parser = argparse.ArgumentParser(); edlt_control_cli.options(parser, 'applications')
        editor = EdltApplications(fixture()); source = editor.snapshot(Session(fixture()).values())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cache.json'; path.write_text(json.dumps(cache_for(editor, source).as_dict()))
            args = parser.parse_args(['--metadata', str(path), '--select', 'secondary=0xff', '--select', 'primary=057', '--select', 'secondary=56'])
            settings = edlt_control_cli.settings(args, 'applications')
            self.assertEqual([edit.as_dict() for edit in settings['edits']], [
                {'field': 'secondary', 'address': 255}, {'field': 'primary', 'address': 57}, {'field': 'secondary', 'address': 56}])
            self.assertEqual(editor.plan(source, **settings).before_save['Application'], (57, 56))

    def test_corridor_order_and_bad_options_before_metadata_io(self):
        parser = argparse.ArgumentParser(); edlt_control_cli.options(parser, 'corridor')
        args = parser.parse_args(['--metadata', '/missing-owned-cache', '--edit', 'link_group=255', '--edit', 'seconds=300', '--edit', 'link_group=42'])
        with patch.object(Path, 'open', side_effect=AssertionError('Invalid edits must not read metadata')):
            for bad in ('seconds=65536', 'seconds=0b100', 'seconds=0o100', 'link_group=-1', 'unknown=1', 'seconds=nope', 'seconds', 'seconds='):
                args.edit = [bad]
                with self.assertRaises(ValueError): edlt_control_cli.settings(args, 'corridor')

    def test_duplicate_metadata_and_file_limit_are_explicit(self):
        parser = argparse.ArgumentParser(); edlt_control_cli.options(parser, 'applications')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cache.json'; args = parser.parse_args(['--metadata', str(path)])
            path.write_text('{"format":"x","format":"y"}')
            with self.assertRaisesRegex(ValueError, 'Duplicate key'): edlt_control_cli.settings(args, 'applications')
            path.write_bytes(b' ' * 257)
            with patch.object(edlt_control_cli, 'MAX_CACHE_BYTES', 256):
                with self.assertRaisesRegex(ValueError, 'exceeds'): edlt_control_cli.settings(args, 'applications')


if __name__ == '__main__': unittest.main()
