from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cbus_toolkit import cli, toolkit_update_revocation as subject, toolkit_update_revocation_cli as boundary
from tests.test_toolkit_update_revocation import CAPTURE_AT, captured, fixture, signer, encode


class RevocationCLITests(unittest.TestCase):
    def invoke(self,*args,status=0):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err),patch('socket.socket',side_effect=AssertionError('No network')),patch('ssl.create_default_context',side_effect=AssertionError('No TLS/store')):
            result=cli.main(list(map(str,args)))
        self.assertEqual(result,status,out.getvalue()+err.getvalue())
        return json.loads(out.getvalue() or err.getvalue())

    def files(self,folder):
        source=Path(folder)/'revocations.json';source.write_bytes(encode(captured()))
        certificate=Path(folder)/'signer.der';certificate.write_bytes(signer())
        return source,certificate

    def test_two_actual_responses_exact_file_and_normalized_data_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            source,certificate=self.files(folder)
            for name in ('leaf','root'):
                source.write_text(fixture()['raw_responses'][name])
                original=source.read_bytes();der=certificate.read_bytes()
                result=self.invoke('update-revocation-stages',source,'--signer-certificate',certificate,'--at-utc',CAPTURE_AT,'--response')
                self.assertTrue(all(x['status']=='passed' for x in result['stages']))
                self.assertEqual(result['source']['file_sha256'],hashlib.sha256(original).hexdigest())
                self.assertEqual(result['source']['selected_data_sha256'],hashlib.sha256(subject.select_revocation_data(original)).hexdigest())
                self.assertIn('not an original byte slice',result['source']['selected_data_representation'])
                self.assertEqual(result['publisher_trust']['status'],'not_evaluated')
                self.assertNotIn('not_revoked',result)
                self.assertEqual(source.read_bytes(),original);self.assertEqual(certificate.read_bytes(),der)

    def test_three_exit_codes_independent_stage_meaning(self):
        with tempfile.TemporaryDirectory() as folder:
            source,certificate=self.files(folder)
            command=('update-revocation-stages',source,'--signer-certificate',certificate,'--at-utc',CAPTURE_AT)
            self.invoke(*command)
            data=captured();data['revokedCertificates']=['0'*40];source.write_bytes(encode(data))
            result=self.invoke(*command,status=1)
            self.assertEqual(result['stages'][-1]['status'],'failed')
            data=captured();data['unknown']={};source.write_bytes(encode(data))
            result=self.invoke(*command,status=2)
            self.assertEqual(result['stages'][0]['status'],'unsupported')
            source.write_bytes(encode(captured()))
            with patch.object(subject,'_load_certificate',side_effect=ImportError('missing')):
                self.invoke(*command,status=2)
            self.invoke('update-revocation-stages',source,'--signer-certificate',certificate,'--at-utc','2040-01-01T00:00:00Z',status=1)

    def test_clock_and_regular_file_admission_before_crypto(self):
        with patch.object(boundary,'_read',side_effect=AssertionError('No I/O')):
            self.invoke('update-revocation-stages','/owned/missing','--signer-certificate','/owned/missing.der','--at-utc','bad',status=1)
        with tempfile.TemporaryDirectory() as folder:
            source,certificate=self.files(folder)
            command=('update-revocation-stages',source,'--signer-certificate',certificate,'--at-utc',CAPTURE_AT)
            with patch.object(subject,'_load_certificate',side_effect=AssertionError('No crypto')):
                for raw in (b'{"x":1,"x":2}',b'{"x":'+b'9'*100000+b'}',b'{"x":"\\ud800"}',b'['*33+b'0'+b']'*33):
                    source.write_bytes(raw);self.invoke(*command,status=1)
            source.write_bytes(encode(captured()))
            link=Path(folder)/'link';link.symlink_to(source)
            paths=[Path(folder),link]
            if hasattr(os,'mkfifo'):
                fifo=Path(folder)/'fifo';os.mkfifo(fifo);paths.append(fifo)
            for path in paths:
                with patch('os.open',side_effect=AssertionError('Do not open a FIFO/link/directory')):
                    self.invoke('update-revocation-stages',path,'--signer-certificate',certificate,'--at-utc',CAPTURE_AT,status=1)
            source.write_bytes(b'{"data":{},"success":1,"statusCode":200}')
            self.invoke(*command,'--response',status=1)

    def test_main_first_interruption_identity_fallback_and_stale_rejection(self):
        class Refuse(KeyboardInterrupt):
            def __setattr__(self,name,value):
                if name=='toolkit_update_revocation_evidence':raise SystemExit('attachment refused')
                super().__setattr__(name,value)
        first=Refuse('original')
        with tempfile.TemporaryDirectory() as folder:
            source,certificate=self.files(folder)
            command=['update-revocation-stages',str(source),'--signer-certificate',str(certificate),'--at-utc',CAPTURE_AT]
            args=cli.build_parser().parse_args(command)
            with patch.object(subject,'_verify_signature',side_effect=first):
                with self.assertRaises(KeyboardInterrupt) as observed:boundary.run(args)
            self.assertIs(observed.exception,first)
            evidence=boundary.error_payload(first,args)['toolkit_update_revocation_evidence']
            self.assertEqual(evidence['source']['file_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(boundary.error_payload(KeyboardInterrupt('other'),args),{})
            args.at_utc='bad'
            with self.assertRaises(ValueError):boundary.run(args)
            self.assertEqual(boundary.error_payload(first,args),{})
            with patch.object(subject,'_verify_signature',side_effect=first):
                result=self.invoke(*command,status=130)
            self.assertTrue(result['toolkit_update_revocation_evidence']['interrupted'])

    def test_secondary_export_failure_preserves_primary_and_source(self):
        first=KeyboardInterrupt('original');later=SystemExit('secondary export')
        with tempfile.TemporaryDirectory() as folder:
            source,certificate=self.files(folder)
            with patch.object(subject,'_verify_signature',side_effect=first),patch.object(subject.RevocationStageReport,'as_dict',side_effect=later):
                result=self.invoke('update-revocation-stages',source,'--signer-certificate',certificate,'--at-utc',CAPTURE_AT,status=130)
            evidence=result['toolkit_update_revocation_evidence']
            self.assertTrue(evidence['evidence_export_failed']);self.assertTrue(evidence['original_error_retained'])
            self.assertEqual(evidence['source']['file_sha256'],hashlib.sha256(source.read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
