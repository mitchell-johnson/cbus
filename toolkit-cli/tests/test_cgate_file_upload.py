"""Public binary FILE upload, exact framing and preconnection refusal."""
import base64
from pathlib import Path
import json
import select
import socket
import subprocess
import sys
import tempfile
import unittest

from cbus_toolkit.file_transfer import MAX_UPLOAD_BYTES, prepare_upload
from tests.test_cgate import peer


class FileUploadTests(unittest.TestCase):
    def invoke(self, endpoint, source, path='owned.bin', *, expected=0):
        result = subprocess.run([sys.executable, '-m', 'cbus_toolkit', 'cgate', '--host', endpoint[0],
                                 '--port', str(endpoint[1]), '--timeout', '1', 'file-upload', path,
                                 str(source), '--project', 'OWNED'], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout or result.stderr)

    def test_binary_and_empty_uploads_send_one_bound_document_after_explicit_selection(self):
        for data in (b'\x00owned\xff', b''):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / 'source.bin'; source.write_bytes(data)
                with peer([[b'[1] 200 OK.\r\n'], [], [], [b'[2] 200 OK.\r\n']]) as (endpoint, sent):
                    result = self.invoke(endpoint, source)
                delimiter = sent[1].decode().strip().split(' << ')[1]
                self.assertEqual(sent, [b'[1] PROJECT USE OWNED\r\n',
                                       f'[2] FILE UPLOAD owned.bin << {delimiter}\r\n'.encode(),
                                       base64.b64encode(data) + b'\n', delimiter.encode() + b'\r\n'])
                self.assertTrue(result['upload_completed'])
                self.assertEqual(result['bytes'], len(data))
                self.assertFalse(result['project_save_requested'])

    def test_refusal_unknown_completion_and_lost_reply_do_not_replay_upload(self):
        for reply in ([b'[2] 201 Unknown success\r\n'], [b'[2] 202 Queued\r\n'],
                      [b'[2] 600 Confirmation required\r\n'], [b'[2] 408 Refused\r\n'], []):
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / 'source.bin'; source.write_bytes(b'a')
                with peer([[b'[1] 200 OK.\r\n'], [], [], reply]) as (endpoint, sent):
                    result = self.invoke(endpoint, source, expected=1)
                self.assertIn('error', result)
                self.assertNotIn('upload_completed', result)
                self.assertEqual(len(sent), 4)
                self.assertEqual(sent[0], b'[1] PROJECT USE OWNED\r\n')
                self.assertEqual(sent[2], b'YQ==\n')

    def test_invalid_path_missing_large_and_nonregular_inputs_refuse_before_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'valid'; source.write_bytes(b'owned')
            large = root / 'large'
            with large.open('wb') as stream:
                stream.truncate(MAX_UPLOAD_BYTES + 1)
            cases = [(source, path) for path in ('../escape', '/absolute', 'C:drive', 'a//b', 'a"b', 'x\nNOOP', '%P%/../escape',
                                                 '~owned.bin', 'owned..bin', '%OWNED%/~owned.bin')]
            cases += [(root / 'missing', 'owned.bin'), (root, 'owned.bin'), (large, 'owned.bin')]
            for selected, path in cases:
                with self.subTest(source=selected, path=path), socket.socket() as trap:
                    trap.bind(('127.0.0.1', 0)); trap.listen(1)
                    result = self.invoke(trap.getsockname(), selected, path, expected=1)
                    self.assertIn('error', result)
                    self.assertFalse(select.select([trap], [], [], .05)[0], 'Invalid upload connected')

    def test_prepared_upload_consumes_one_immutable_binary_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source'; path.write_bytes(b'original\x00')
            plan = prepare_upload('%OWNED%/source.bin', path, project='OWNED')
            path.write_bytes(b'changed')
            self.assertEqual(plan.data, b'original\x00')
            self.assertEqual(base64.b64decode(plan.document), plan.data)


if __name__ == '__main__':
    unittest.main()
