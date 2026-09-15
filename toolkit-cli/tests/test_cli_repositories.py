"""Read-only repository CLI dispatch and literal native framing."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cbus_toolkit import cli
from cbus_toolkit.repositories_cli import run
from tests.test_repositories import LITERAL, Stream, response


class RepositoryCLITests(unittest.TestCase):
    def invoke(self, chunks, *, status=0):
        stream=Stream([b'201 Ready\r\n',*chunks]); output=io.StringIO(); errors=io.StringIO()
        with patch('cbus_toolkit.cgate.socket.create_connection',return_value=stream), redirect_stdout(output), redirect_stderr(errors):
            code=cli.main(['cgate','--host','127.0.0.1','--port','12345','repositories'])
        self.assertEqual(code,status,output.getvalue()+errors.getvalue())
        self.assertEqual(stream.sent,[b'[1] REPOSITORY LIST\r\n']); self.assertTrue(stream.closed)
        return json.loads(output.getvalue() or errors.getvalue())

    def test_unique_unknown_multiple_and_empty_are_successful_read_observations(self):
        cases=[(LITERAL,'unique'),(tuple(s.replace('current=yes','current=no') for s in LITERAL),'unknown'),
               (tuple(s.replace('current=no','current=yes') for s in LITERAL),'multiple'),
               (('124 no repositories found',),'unknown')]
        for lines,state in cases:
            with self.subTest(state=state,lines=lines):
                wire=('\r\n'.join('[1] '+line for line in lines)+'\r\n').encode()
                value=self.invoke([wire[:18],wire[18:]])
                self.assertEqual(value['current_state'],state)
                self.assertTrue(value['read_only']); self.assertFalse(value['repository_changed'])
                if state!='unique': self.assertIsNone(value['current_index'])

    def test_malformed_native_rejection_and_truncated_capture_fail_without_second_command(self):
        for wire in (b'[1] 123 index=2 type=file path=/owned current=yes\r\n',
                     b'[1] 408 Operation failed\r\n',
                     b'[1] 123-index=1 type=file path=/owned current=yes\r\n'):
            with self.subTest(wire=wire): self.assertIn('error',self.invoke([wire],status=1))

    def test_interruption_closes_and_exits130_without_replay(self):
        value=self.invoke([KeyboardInterrupt('owned cancellation')],status=130)
        self.assertIn('error',value)

    def test_adapter_preserves_tls_factory_arguments(self):
        raw=response(*LITERAL); calls=[]; tls=object()
        class Client:
            def __enter__(self): return self
            def __exit__(self,*args): calls.append('closed')
            def command(self,text): calls.append(text); return raw
        def factory(*args,**kwargs):
            self.assertEqual(args,('owned.example',20200)); self.assertEqual(kwargs,{'timeout':7.5,'ssl_context':tls})
            return Client()
        value,code=run(SimpleNamespace(host='owned.example',port=20200,timeout=7.5),factory,tls)
        self.assertEqual(code,0); self.assertEqual(value['current_index'],2)
        self.assertEqual(calls,['REPOSITORY LIST','closed'])

    def test_selector_arguments_are_absent_and_rejected_before_connection(self):
        with patch('cbus_toolkit.cgate.socket.create_connection',side_effect=AssertionError('must not connect')):
            for extra in (['use','2'],['--index','2']):
                with self.subTest(extra=extra),redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        cli.main(['cgate','repositories',*extra])
                    self.assertEqual(caught.exception.code,2)
