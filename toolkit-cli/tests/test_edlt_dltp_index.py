"""SHA-256-bound Toolkit DLTP index and ICON dynamic-label resolution."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.edlt import EdltError
from cbus_toolkit.edlt_dltp_index import (
    DltpIndexError, load_dltp_index, parse_dltp_index,
)
from cbus_toolkit.edlt_parent_metadata import plan_native_parent_metadata
from cbus_toolkit.edlt_scene_metadata import resolve_native_scene_metadata
import tests.test_edlt_parent_metadata as parent_tests
import tests.test_edlt_scene_metadata as scene_tests
from tests.test_edlt_scene_metadata import SceneMetadataClient, operations

ROOT = Path(__file__).resolve().parents[1]
# Pinned public fact about the private Toolkit 1.18.0.2754 install.  The index
# and its images are vendor files and are never committed.
VENDOR_DLTP_INDEX_SHA256 = 'c6cca64deaed7bb5ad814b2aaf4c37b580396bf38c057aae8bd616fadfd26310'
VENDOR_DLTP_INDEX_ROWS = 91
VENDOR_APP_CANDIDATES = (
    Path(os.environ.get('CBUS_TOOLKIT_EXE',
                        ROOT / 'research/vendor/toolkit/app/CBusToolkit.exe')).parent,
    Path('/Volumes/external/mac-mini-offload/source-cbus/'
         'toolkit-cli-research-vendor/toolkit/app'),
)
VENDOR_APP = next((path for path in VENDOR_APP_CANDIDATES
                   if (path / 'Images').is_dir()), None)

INDEX = b'1,Synthetic One,01 - One.bmp\r\n2,Synthetic Two,02 - Two.bmp\r\n17,Seventeen,17 - X.BMP\r\n'
IMAGES = {'01 - One.bmp': b'BM\x01', '02 - two.bmp': b'BM\x02', '17 - X.BMP': b'BM\x03'}


def install(root, index=INDEX, images=IMAGES, *, images_dir='images', dltp_dir='dltp',
            index_name='INDEX.TXT'):
    """Synthetic install; component case deliberately differs from the source."""
    directory = Path(root) / images_dir / dltp_dir
    directory.mkdir(parents=True)
    (directory / index_name).write_bytes(index)
    for name, data in images.items():
        (directory / name).write_bytes(data)
    return Path(root), hashlib.sha256(index).hexdigest()


class DltpIndexTests(unittest.TestCase):
    def test_case_insensitive_binding_and_exact_icon_match(self):
        with tempfile.TemporaryDirectory() as root:
            app, digest = install(root)
            index = load_dltp_index(app, expected_sha256=digest)
        self.assertEqual(index.index_sha256, digest)
        self.assertEqual([(row.key, row.name, row.file_name) for row in index.entries],
                         [(1, 'Synthetic One', '01 - One.bmp'),
                          (2, 'Synthetic Two', '02 - Two.bmp'),
                          (17, 'Seventeen', '17 - X.BMP')])
        self.assertEqual(index.entries[1].file_sha256, hashlib.sha256(b'BM\x02').hexdigest())
        # TagDLT.PopulateImage compares key.ToString() == TagValue exactly.
        for value, expected in (('17', True), ('1', True), ('017', False), (' 17', False),
                                ('+17', False), ('3', False), ('', False)):
            self.assertIs(index.image_present(value), expected, value)
        self.assertFalse(index.as_dict()['images_decoded'])
        self.assertEqual(index.evidence()['keys'], [1, 2, 17])

    def test_sha256_binding_is_required_and_exact(self):
        with tempfile.TemporaryDirectory() as root:
            app, digest = install(root)
            for bad in (None, digest.upper(), digest[:-1], 'g' * 64):
                with self.subTest(bad=bad), self.assertRaisesRegex(DltpIndexError, 'lowercase hex'):
                    load_dltp_index(app, expected_sha256=bad)
            with self.assertRaisesRegex(DltpIndexError, 'differs'):
                load_dltp_index(app, expected_sha256='0' * 64)

    def test_strict_parser_rejects_malformed_and_duplicate_rows(self):
        self.assertEqual(parse_dltp_index(b'5,Five,a.bmp'), ((5, 'Five', 'a.bmp'),))
        self.assertEqual(parse_dltp_index(b'5,Five,a.bmp\n6,Six,b.bmp\r7,S,c.bmp\r\n'),
                         ((5, 'Five', 'a.bmp'), (6, 'Six', 'b.bmp'), (7, 'S', 'c.bmp')))
        for raw, message in (
                (b'', '1 byte'),
                (b'\xef\xbb\xbf1,A,a.bmp', 'BOM'),
                (b'1,A,a.bmp\0', 'BOM or NUL'),
                (b'1,A,\xff.bmp', 'UTF-8'),
                (b'1,A', 'three fields'),
                (b'1,A,B,a.bmp', 'three fields'),
                (b'1,A,a.bmp\r\n\r\n2,B,b.bmp', 'three fields'),
                (b'01,A,a.bmp', 'canonical Int32'),
                (b'+1,A,a.bmp', 'canonical Int32'),
                (b'-1,A,a.bmp', 'canonical Int32'),
                (b' 1,A,a.bmp', 'canonical Int32'),
                (b'2147483648,A,a.bmp', 'canonical Int32'),
                (b'1,,a.bmp', 'empty name'),
                (b'1,A\tB,a.bmp', 'control'),
                (b'1,A,sub/a.bmp', 'bare .bmp'),
                (b'1,A,..\\a.bmp', 'bare .bmp'),
                (b'1,A,a.png', 'bare .bmp'),
                (b'1,A,a.bmp \r\n', 'bare .bmp'),
                (b'1,A,a.bmp\r\n1,B,b.bmp', 'duplicates key'),
                (b'1,A,a.bmp\r\n2,B,A.BMP', 'duplicates an image'),
        ):
            with self.subTest(raw=raw), self.assertRaisesRegex(DltpIndexError, message):
                parse_dltp_index(raw)

    def test_unresolved_or_invalid_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            images = dict(IMAGES); images.pop('17 - X.BMP')
            app, digest = install(root, images=images)
            with self.assertRaisesRegex(DltpIndexError, "17 - X.BMP"):
                load_dltp_index(app, expected_sha256=digest)
        with tempfile.TemporaryDirectory() as root:
            app, digest = install(root, images={**IMAGES, '02 - two.bmp': b'PNG'})
            with self.assertRaisesRegex(DltpIndexError, 'not a BMP'):
                load_dltp_index(app, expected_sha256=digest)
        with tempfile.TemporaryDirectory() as root:
            app, digest = install(root, index_name='other.txt')
            with self.assertRaisesRegex(DltpIndexError, 'Index.txt'):
                load_dltp_index(app, expected_sha256=digest)
        with tempfile.TemporaryDirectory() as root:
            app, digest = install(root, index_name='real.txt')
            (app / 'images/dltp/Index.txt').symlink_to(app / 'images/dltp/real.txt')
            with self.assertRaisesRegex(DltpIndexError, 'wrong type'):
                load_dltp_index(app, expected_sha256=digest)

    def test_ambiguous_case_variants_fail_closed_on_case_sensitive_storage(self):
        with tempfile.TemporaryDirectory() as root:
            app, digest = install(root, images_dir='Images', dltp_dir='DLTP')
            try:
                (app / 'IMAGES').mkdir()
            except FileExistsError:
                self.skipTest('Temporary storage is case-insensitive')
            with self.assertRaisesRegex(DltpIndexError, 'exactly one'):
                load_dltp_index(app, expected_sha256=digest)

    @unittest.skipUnless(VENDOR_APP is not None, 'Private Toolkit install is absent')
    def test_pinned_vendor_index_fact(self):
        index = load_dltp_index(VENDOR_APP, expected_sha256=VENDOR_DLTP_INDEX_SHA256)
        self.assertEqual(len(index.entries), VENDOR_DLTP_INDEX_ROWS)
        self.assertEqual([row.key for row in index.entries], list(range(1, 92)))


class ParentIconTests(unittest.TestCase):
    """ICON variants resolve only with a supplied bound index."""
    # Reuse the fixture without collecting the imported test class again.
    setUp = parent_tests.ParentMetadataTests.setUp
    manager = parent_tests.ParentMetadataTests.manager
    OPERATIONS = (
        {'op': 'lighting', 'page': 1, 'position': 1, 'group': 12, 'mode': 'dimmer',
         'label_type': 'dynamic-icon', 'label_index': 1},
        {'op': 'measurement', 'page': 1, 'position': 2, 'device_id': 1, 'channel': 1},
    )

    def icon_group(self, tags):
        self.client.applications[56]['groups'][12] = {
            'oid': parent_tests.oid(120), 'tag': 'Lighting group', 'levels': (),
            'tags': tags}

    def plan(self, **kwargs):
        return plan_native_parent_metadata(self.client.xml(), '//TEST/254/p/20', self.values,
                                           self.editor, self.OPERATIONS, **kwargs)

    def index(self):
        with tempfile.TemporaryDirectory() as root:
            app, digest = install(root)
            return load_dltp_index(app, expected_sha256=digest)

    def test_icon_resolves_with_index_and_other_image_types_still_fail_closed(self):
        self.icon_group(({'variant': 1, 'type': 'ICON', 'value': '17'},
                         {'variant': 2, 'type': 'ICON', 'value': '017'},
                         {'variant': 3, 'type': 'TEXT', 'value': '17'}))
        with self.assertRaisesRegex(ValueError, 'not derivable from DBGETXML'):
            self.plan()
        index = self.index()
        plan = self.plan(dltp_index=index)
        self.assertEqual(plan.cache.find(56, 12).dynamic_images, (False, True, False, False))
        document = plan.as_dict()
        dependency = next(row for row in document['parent_transaction'][
            'operation_metadata_dependencies'] if row.get('field') == 'dynamic_images')
        self.assertEqual((dependency['group'], dependency['variant'], dependency['is_icon']),
                         (12, 1, True))
        self.assertTrue(document['icon_dynamic_labels_resolved'])
        self.assertEqual(document['toolkit_dltp_index']['index_sha256'], index.index_sha256)
        self.assertFalse(document['project_images_loaded'])

        # An ICON value absent from the index has no Image, so the original
        # resolves the variant as text and the explicit icon binding is refused.
        self.icon_group(({'variant': 1, 'type': 'ICON', 'value': '99'},))
        with self.assertRaisesRegex(EdltError, 'dynamic-text'):
            self.plan(dltp_index=index)
        for tag_type, value in (('DYNAMIC', 'image.png'), ('FONT', 'font,12')):
            self.icon_group(({'variant': 1, 'type': 'ICON', 'value': '17'},
                             {'variant': 0, 'type': tag_type, 'value': value}))
            with self.subTest(tag_type=tag_type), self.assertRaisesRegex(
                    ValueError, 'not derivable from DBGETXML'):
                self.plan(dltp_index=index)

    def test_native_manager_keeps_the_index_for_freshness_and_reload(self):
        self.icon_group(({'variant': 1, 'type': 'ICON', 'value': '2'},))
        index = self.index()
        manager, _session, programmer = self.manager()
        with self.assertRaisesRegex(ValueError, 'load_dltp_index'):
            type(manager)(self.client, self.editor, dltp_index=object())
        manager = type(manager)(self.client, self.editor, programmer=programmer,
                                dltp_index=index)
        plan = manager.plan('//TEST/254/p/20', operations=self.OPERATIONS,
                            exclusive_project=True)
        self.assertIs(plan.snapshot.dltp_index, index)
        self.assertEqual(plan.cache.find(56, 12).dynamic_images, (False, True, False, False))
        result = manager.apply(plan, backup_project='BACKUP').as_dict()
        self.assertTrue(result['complete'] and result['persistence_verified'])


class SceneIconTests(unittest.TestCase):
    setUp = scene_tests.SceneMetadataTests.setUp

    def test_icon_action_labels_resolve_only_with_the_index(self):
        image = deepcopy(self.client.applications)
        image[202]['groups'][42]['level_tags'] = {
            1: ({'variant': 0, 'type': 'ICON', 'value': '17'},
                {'variant': 3, 'type': 'ICON', 'value': '4'}),
        }
        client = SceneMetadataClient(self.spec)
        client.applications = image
        client.values = deepcopy(self.client.values)
        with self.assertRaisesRegex(ValueError, 'image metadata is not derivable'):
            resolve_native_scene_metadata(client.xml(), '//TEST/254/p/20', self.values,
                                          self.editor.engine, operations('sync'))
        with tempfile.TemporaryDirectory() as root:
            app, digest = install(root)
            index = load_dltp_index(app, expected_sha256=digest)
        resolved = resolve_native_scene_metadata(
            client.xml(), '//TEST/254/p/20', self.values, self.editor.engine,
            operations('sync'), dltp_index=index)
        labels = next(row for row in resolved.cache.level_labels
                      if (row.group, row.action) == (42, 1)).labels
        self.assertEqual([(row.value, row.name, row.image_present) for row in labels],
                         [('0', '17', True), ('1', '', False), ('2', '', False), ('3', '4', False)])
        self.assertTrue(resolved.as_dict()['icon_dynamic_labels_resolved'])
        image[202]['groups'][42]['level_tags'][1] += (
            {'variant': 1, 'type': 'DYNAMIC', 'value': 'image.png'},)
        client.applications = image
        with self.assertRaisesRegex(ValueError, 'image metadata is not derivable'):
            resolve_native_scene_metadata(client.xml(), '//TEST/254/p/20', self.values,
                                          self.editor.engine, operations('sync'),
                                          dltp_index=index)


class PresentationCLITests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = cli.main(list(map(str, arguments)))
        return status, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_options_require_automatic_metadata_and_paired_binding(self):
        with tempfile.TemporaryDirectory() as root:
            metadata = Path(root) / 'metadata.json'
            metadata.write_text('{}')
            values = Path(root) / 'values.json'
            values.write_text('{}')
            ops = Path(root) / 'operations.json'
            ops.write_text('[]')
            for extra, message in (
                    (['--toolkit-dltp-dir', root], 'supplied together'),
                    (['--display-preferences', metadata], 'require --project-xml'),
            ):
                with self.subTest(extra=extra), patch.object(
                        cli, '_edlt_parent_transaction', return_value=None):
                    status, result = self.invoke([
                        'edlt', 'parent-transaction-plan', values, '--metadata', metadata,
                        '--operations', ops, *extra])
                    self.assertNotEqual(status, 0)
                    self.assertIn(message, json.dumps(result))


if __name__ == '__main__':
    unittest.main()
