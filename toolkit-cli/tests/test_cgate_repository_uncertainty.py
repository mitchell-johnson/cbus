"""Owned loopback replies pin the repository uncertainty transport boundary."""
from contextlib import contextmanager
import re
import socketserver
import threading
import unittest
from unittest import mock

from cbus_toolkit.cgate import (
    CGateClient, CGateError, CGateRepositoryUncertainError, CGateResponse,
)


UNCERTAIN = (
    '500 Repository durability uncertain; inspect state before further changes; do not replay'
)


@contextmanager
def repository_peer(responder):
    """A real socket records whole commands/documents and observes client EOF."""
    commands, documents, connections, errors = [], [], [], []
    ended = threading.Event()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            connections.append(self.client_address)
            self.connection.settimeout(2)
            try:
                self.connection.sendall(b'201 Service ready: owned repository fixture\r\n')
                while raw := self.rfile.readline():
                    match = re.fullmatch(rb'\[([0-9]+)\] (.+)\r\n', raw)
                    if match is None:
                        raise AssertionError('Invalid numeric-tag command: ' + repr(raw))
                    tag, body = match.groups()
                    document = None
                    if b' << ' in body:
                        body, delimiter = body.split(b' << ', 1)
                        rows = []
                        while (row := self.rfile.readline()).rstrip(b'\r\n') != delimiter:
                            if not row:
                                raise AssertionError('Incomplete document')
                            rows.append(row)
                        document = b''.join(rows).decode('utf-8')
                    command = body.decode('utf-8')
                    commands.append(command)
                    documents.append(document)
                    response = responder(command, document)
                    lines = response.lines if isinstance(response, CGateResponse) else response
                    self.connection.sendall(b''.join(
                        b'[' + tag + b'] ' + line.encode('utf-8') + b'\r\n'
                        for line in lines))
            except BaseException as error:
                errors.append(error)
            finally:
                ended.set()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={'poll_interval': 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_address, commands, documents, connections, ended
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        if errors:
            raise errors[0]


class RepositoryUncertaintyTransportTests(unittest.TestCase):
    @staticmethod
    def issue(client, document):
        if document:
            return client.command_document('DBSETXML //LAB/Description', '<Description>Owned</Description>')
        return client.command('PROJECT SAVE LAB')

    def test_exact_uncertainty_closes_regular_and_document_streams_with_complete_reply(self):
        for document in (False, True):
            with self.subTest(document=document), repository_peer(
                    lambda *_: ('500-Repository replacement visible', UNCERTAIN)) as peer:
                address, commands, documents, connections, ended = peer
                with CGateClient(*address, timeout=1) as client:
                    with self.assertRaises(CGateRepositoryUncertainError) as caught:
                        self.issue(client, document)
                    error = caught.exception
                    self.assertIsInstance(error, CGateError)
                    self.assertTrue(error.repository_state_uncertain)
                    self.assertEqual(error.response, CGateResponse(
                        ('500-Repository replacement visible', UNCERTAIN), UNCERTAIN, 500))
                    self.assertFalse(client.connected)
                    self.assertEqual(client._buffer, bytearray())
                    for operation in (lambda: client.command('PROJECT SAVE LAB'),
                                      lambda: client.command_document('DBSETXML //LAB/Description', 'Retry')):
                        with self.assertRaisesRegex(RuntimeError, 'not connected'):
                            operation()
                    self.assertTrue(ended.wait(1), 'Peer did not observe client EOF')
                    self.assertEqual(len(connections), 1)
                    self.assertEqual(commands, ['DBSETXML //LAB/Description' if document else 'PROJECT SAVE LAB'])
                    self.assertEqual(documents, ['<Description>Owned</Description>\n' if document else None])

    def test_generic_errors_and_near_matches_keep_stream_synchronized(self):
        for final in ('500 Database commit failed; change rolled back',
                      UNCERTAIN + '.', UNCERTAIN + ' ',
                      UNCERTAIN.replace('Repository', 'repository'),
                      UNCERTAIN.replace('500 ', '400 ', 1)):
            for document in (False, True):
                replies = iter(((final,), ('200 OK.',)))
                with self.subTest(final=final, document=document), repository_peer(
                        lambda *_: next(replies)) as peer:
                    address, commands, _, connections, ended = peer
                    with CGateClient(*address, timeout=1) as client:
                        with self.assertRaises(CGateError) as caught:
                            self.issue(client, document)
                        self.assertIs(type(caught.exception), CGateError)
                        self.assertFalse(getattr(caught.exception, 'repository_state_uncertain', False))
                        self.assertEqual(caught.exception.response.final, final)
                        self.assertTrue(client.connected)
                        self.assertEqual(client.command('NOOP').final, '200 OK.')
                    self.assertTrue(ended.wait(1))
                    self.assertEqual(commands[-1], 'NOOP')
                    self.assertEqual(len(commands), 2)
                    self.assertEqual(len(connections), 1)

    def test_secondary_close_failure_keeps_uncertainty_and_reply(self):
        with repository_peer(lambda *_: (UNCERTAIN,)) as peer:
            address, commands, _, _, ended = peer
            with CGateClient(*address, timeout=1) as client:
                close = client.close
                cleanup_error = OSError('owned close diagnostic')

                def fail_close():
                    close()
                    raise cleanup_error

                with mock.patch.object(client, 'close', side_effect=fail_close):
                    with self.assertRaises(CGateRepositoryUncertainError) as caught:
                        client.command('PROJECT SAVE LAB')
                self.assertEqual(caught.exception.response.final, UNCERTAIN)
                self.assertEqual(caught.exception.cgate_cleanup_errors, (cleanup_error,))
                self.assertFalse(client.connected)
                self.assertTrue(ended.wait(1))
                self.assertEqual(commands, ['PROJECT SAVE LAB'])
