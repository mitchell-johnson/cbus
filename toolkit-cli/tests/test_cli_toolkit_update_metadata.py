from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli, toolkit_update_metadata as metadata, toolkit_update_metadata_cli as boundary
from tests.test_toolkit_update_metadata import AT, captured, encode, fixture, leaf, owned_der, signed_node


class MetadataCLITests(unittest.TestCase):
    def invoke(self, *args, status=0):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
             patch('socket.socket', side_effect=AssertionError('No network')), \
             patch('ssl.create_default_context', side_effect=AssertionError('No TLS/trust store')):
            result = cli.main(list(map(str, args)))
        self.assertEqual(result, status, out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def files(self, folder, node=None, der=None):
        source = Path(folder)/'node.json'; source.write_bytes(encode(captured() if node is None else node))
        certificate = Path(folder)/'certificate.der'; certificate.write_bytes(leaf() if der is None else der)
        return source, certificate

    def test_actual_seven_catalogue_selection_normalization_and_no_trust_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            source, certificate = self.files(folder)
            source.write_bytes(fixture()['raw_catalogue_json'].encode())
            before = {p:p.read_bytes() for p in (source, certificate)}
            for node in json.loads(before[source])['data']:
                result = self.invoke('update-metadata-stages', source, '--node-id', node['nodeId'],
                    '--certificate', certificate, '--at-utc', '2026-09-15T02:34:07.1234567Z')
                self.assertTrue(all(row['status']=='passed' for row in result['stages']))
                self.assertEqual(result['source']['file_sha256'], hashlib.sha256(before[source]).hexdigest())
                selected = metadata.select_node(before[source], node_id=node['nodeId'])
                self.assertEqual(result['source']['selected_node_sha256'], hashlib.sha256(selected).hexdigest())
                self.assertEqual(result['source']['selected_node_id'], node['nodeId'])
                self.assertIn('not an original byte slice', result['source']['selected_node_representation'])
                self.assertEqual(result['publisher_trust']['status'], 'not_evaluated')
                self.assertNotIn('metadata_signature_verified', result)
            self.assertTrue(all(path.read_bytes()==value for path,value in before.items()))

    def test_stage_exit_codes_mean_diagnostics_only(self):
        with tempfile.TemporaryDirectory() as folder:
            source, certificate = self.files(folder)
            self.invoke('update-metadata-stages', source, '--certificate', certificate, '--at-utc', AT)
            node = captured(); node['nodeName'] = 'changed signed name'; source.write_bytes(encode(node))
            result = self.invoke('update-metadata-stages', source, '--certificate', certificate, '--at-utc', AT, status=1)
            self.assertEqual(result['stages'][-1]['status'], 'failed')
            node = captured(); node['nodeName'] = '2025-02-17T13:45:00+13:45'; source.write_bytes(encode(node))
            result = self.invoke('update-metadata-stages', source, '--certificate', certificate, '--at-utc', AT, status=2)
            self.assertEqual(result['stages'][0]['status'], 'unsupported')
            with patch.object(metadata, '_load_certificate', side_effect=ImportError('dependency absent')):
                source.write_bytes(encode(captured()))
                self.invoke('update-metadata-stages', source, '--certificate', certificate, '--at-utc', AT, status=2)

    def test_unknown_der_key_algorithm_returns_json_status_two(self):
        rsa_oid = bytes.fromhex('06092a864886f70d010101')
        der = leaf().replace(rsa_oid, rsa_oid[:-1] + b'\x63', 1)
        with tempfile.TemporaryDirectory() as folder:
            source, certificate = self.files(folder, der=der)
            result = self.invoke('update-metadata-stages', source, '--certificate', certificate, '--at-utc', AT, status=2)
        self.assertEqual(result['stages'][2]['status'], 'unsupported')
        self.assertEqual(result['stages'][2]['error']['type'], 'UnsupportedAlgorithm')

    def test_invalid_clock_and_node_id_precede_file_io_and_json_bounds_precede_crypto(self):
        with patch.object(boundary, '_read', side_effect=AssertionError('No file I/O')):
            for extra in (('--at-utc','bad'), ('--at-utc',AT,'--node-id','')):
                self.invoke('update-metadata-stages', '/owned/missing', '--certificate', '/owned/missing.der', *extra, status=1)
        with tempfile.TemporaryDirectory() as folder:
            source, certificate = self.files(folder)
            with patch.object(metadata, '_load_certificate', side_effect=AssertionError('No crypto')):
                for content in (b'{"x":1,"x":2}', b'{"x":'+b'9'*100000+b'}', b'{"x":"\\ud800"}', b' '* (metadata.MAX_NODE_BYTES+1)):
                    source.write_bytes(content)
                    self.invoke('update-metadata-stages', source, '--certificate', certificate, '--at-utc', AT, status=1)

    def test_nonregular_input_and_open_race_are_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as folder:
            source, certificate = self.files(folder)
            link = Path(folder)/'link'; link.symlink_to(source)
            for path in (Path(folder), link):
                with patch.object(boundary.os, 'open', side_effect=AssertionError('No open for nonregular path')):
                    self.invoke('update-metadata-stages', path, '--certificate', certificate, '--at-utc', AT, status=1)
            if hasattr(os, 'mkfifo'):
                fifo = Path(folder)/'fifo'; os.mkfifo(fifo)
                with patch.object(boundary.os, 'open', side_effect=AssertionError('No open for FIFO')):
                    self.invoke('update-metadata-stages', fifo, '--certificate', certificate, '--at-utc', AT, status=1)
                # Swap the regular file only after lstat; O_NONBLOCK prevents an
                # open wait and fstat rejects the resulting descriptor.
                original_open = os.open
                def swap(path, flags):
                    if Path(path) == source:
                        source.unlink(); os.mkfifo(source)
                    return original_open(path, flags)
                with patch.object(boundary.os, 'open', side_effect=swap):
                    self.invoke('update-metadata-stages', source, '--certificate', certificate, '--at-utc', AT, status=1)

    def test_first_file_read_interruption_survives_close_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            source, _ = self.files(folder)
            first = KeyboardInterrupt('original read'); later = SystemExit('secondary close')
            original_close = os.close
            def close(fd):
                original_close(fd); raise later
            with patch.object(boundary.os, 'read', side_effect=first), patch.object(boundary.os, 'close', side_effect=close):
                with self.assertRaises(KeyboardInterrupt) as observed: boundary._read(source, metadata.MAX_NODE_BYTES)
            self.assertIs(observed.exception, first)

    def test_error_export_interruption_cannot_replace_original_in_main(self):
        first = KeyboardInterrupt('original crypto interruption')
        later = SystemExit('secondary evidence export')
        with tempfile.TemporaryDirectory() as folder:
            source, certificate = self.files(folder)
            command = ['update-metadata-stages', source, '--certificate', certificate, '--at-utc', AT]
            with patch.object(metadata, '_verify_signature', side_effect=first), \
                 patch.object(metadata.MetadataStageReport, 'as_dict', side_effect=later):
                result = self.invoke(*command, status=130)
            evidence = result['toolkit_update_metadata_evidence']
            self.assertTrue(evidence['evidence_export_failed'])
            self.assertTrue(evidence['original_error_retained'])
            self.assertEqual(evidence['source']['file_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_main_interrupt_and_same_error_fallback_keep_selection_provenance(self):
        class Reject(KeyboardInterrupt):
            def __setattr__(self, name, value):
                if name == 'toolkit_update_metadata_evidence': raise SystemExit('attachment refused')
                super().__setattr__(name, value)
        with tempfile.TemporaryDirectory() as folder:
            source, certificate = self.files(folder)
            source.write_bytes(fixture()['raw_catalogue_json'].encode())
            command = ['update-metadata-stages', str(source), '--certificate', str(certificate),
                '--at-utc', AT, '--node-id', captured()['nodeId']]
            for first in (Reject('first'), KeyboardInterrupt('first')):
                args = cli.build_parser().parse_args(command)
                with patch.object(metadata, '_verify_signature', side_effect=first):
                    with self.assertRaises(KeyboardInterrupt) as observed: boundary.run(args)
                self.assertIs(observed.exception, first)
                evidence = boundary.error_payload(first, args)['toolkit_update_metadata_evidence']
                self.assertEqual(evidence['source']['file_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(evidence['source']['selected_node_id'], captured()['nodeId'])
                self.assertEqual(boundary.error_payload(KeyboardInterrupt('other'), args), {})
                args.at_utc = 'bad'
                with self.assertRaises(ValueError): boundary.run(args)
                self.assertEqual(boundary.error_payload(first, args), {})
                with patch.object(metadata, '_verify_signature', side_effect=first):
                    result = self.invoke(*command, status=130)
                self.assertTrue(result['toolkit_update_metadata_evidence']['interrupted'])
                self.assertIn('source', result['toolkit_update_metadata_evidence'])


if __name__ == '__main__': unittest.main()
