"""Public FILE export framing, byte admission and preconnection refusals."""
import base64
import hashlib
import json
from pathlib import Path
import select
import socket
import struct
import subprocess
import sys
import tempfile
import unittest

from cbus_toolkit.cli import build_parser
from cbus_toolkit.edlt_parent_transaction_cli import presentation
from cbus_toolkit.edlt_scene_label_images import load_project_images
from tests.test_cgate import peer


def owned_bmp():
    pixels = b'\x00\x00\xff\x00'
    return (b'BM' + struct.pack('<III', 58, 0, 54)
            + struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0)
            + pixels)


class ProjectImageCLITests(unittest.TestCase):
    def invoke(self, endpoint, output, *, project='OWNED', expected=0):
        result = subprocess.run(
            [sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', endpoint[0],
             '--port', str(endpoint[1]), '--timeout', '1', 'edlt-project-images',
             project, '--output', str(output)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_export_downloads_only_source_selected_bmps_in_directory_order(self):
        raw = owned_bmp()
        directory = [b'[1] 304-directory="%PROJ%/OWNED" files=3\r\n',
                     b'[1] 305-name="OWNED-DLTD-Pic0002.bmp" size=58 modified=0\r\n',
                     b'[1] 305-name="ignored.txt" size=1 modified=0\r\n',
                     b'[1] 305 name="OWNED-DLTD-Pic0001.bmp" size=58 modified=0\r\n']
        responses = [directory]
        for number, key in ((2, '0002'), (3, '0001')):
            encoded = base64.b64encode(raw)
            responses.append([
                f'[{number}] 345-Start file download for file: %PROJ%/OWNED/OWNED-DLTD-Pic{key}.bmp\r\n'.encode(),
                *[f'[{number}] 347-'.encode() + encoded[i:i+76] + b'\r\n'
                  for i in range(0, len(encoded), 76)],
                f'[{number}] 346 End file download\r\n'.encode()])
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'images.json'
            with peer(responses) as (endpoint, sent):
                result = self.invoke(endpoint, output)
            self.assertEqual(sent, [b'[1] FILE DIR %PROJ%/OWNED\r\n',
                b'[2] FILE DOWNLOAD %PROJ%/OWNED/OWNED-DLTD-Pic0002.bmp\r\n',
                b'[3] FILE DOWNLOAD %PROJ%/OWNED/OWNED-DLTD-Pic0001.bmp\r\n'])
            self.assertEqual(result['sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            images = load_project_images(output, expected_sha256=result['sha256'])
            self.assertEqual([row.key for row in images.entries], ['0002', '0001'])
            self.assertFalse(result['project_save_requested'])
            self.assertFalse(result['physical_io_requested'])

    def test_empty_directory_creates_explicit_empty_byte_bound_provider(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'images.json'
            with peer([[b'[1] 304 directory="%PROJ%/OWNED" files=0\r\n']]) as (endpoint, sent):
                result = self.invoke(endpoint, output)
            self.assertEqual(len(sent), 1)
            self.assertEqual(load_project_images(output, expected_sha256=result['sha256']).entries, ())

    def test_unknown_or_incomplete_receipts_never_publish_or_retry(self):
        replies = [[b'[1] 200 OK\r\n'], [b'[1] 408 Missing\r\n'], [],
                   [b'[1] 304 directory="%PROJ%/OWNED" files=1\r\n']]
        for reply in replies:
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as root:
                output = Path(root) / 'images.json'
                with peer([reply]) as (endpoint, sent):
                    self.invoke(endpoint, output, expected=1)
                self.assertEqual(len(sent), 1)
                self.assertFalse(output.exists())

    def test_preflight_preserves_existing_output_and_rejects_project_injection(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'existing.json'
            output.write_bytes(b'operator-data')
            for project, destination in [('OWNED', output), ('OWNED\nSAVE', Path(root)/'new.json'),
                                         ('../OWNED', Path(root)/'new.json')]:
                with self.subTest(project=project), socket.socket() as trap:
                    trap.bind(('127.0.0.1', 0)); trap.listen(1)
                    self.invoke(trap.getsockname(), destination, project=project, expected=1)
                    self.assertFalse(select.select([trap], [], [], .05)[0])
            self.assertEqual(output.read_bytes(), b'operator-data')

    def test_image_option_pair_is_admitted_only_with_native_metadata(self):
        parser = build_parser()
        common = ['edlt', 'parent-transaction-plan', 'values.json', '--operations', 'ops.json']
        for source in (['--metadata', 'cache.json'], ['--project-xml', 'project.xml', '--unit', '//OWNED/254/p/20']):
            args = parser.parse_args(common + source + ['--project-images-export', 'images.json'])
            with self.assertRaisesRegex(ValueError, 'must be supplied together'):
                presentation(args)
        args = parser.parse_args(common + ['--metadata', 'cache.json', '--project-images-export',
                                           'images.json', '--project-images-sha256', '0'*64])
        with self.assertRaisesRegex(ValueError, 'require --project-xml or --auto-metadata'):
            presentation(args)


if __name__ == '__main__':
    unittest.main()
