"""Native repository grammar, unambiguous observations and one-request transport."""
from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from cbus_toolkit.cgate import CGateClient, CGateError, CGateResponse
from cbus_toolkit.repositories import NativeRepositories, RepositoryDescriptor, parse_repository_list


def response(*lines, code=None):
    return CGateResponse(tuple(lines), lines[-1], int(lines[-1][:3]) if code is None else code)


LITERAL = (
    '123-index=1 type=sqlite-file path=/owned projects/key=value current=no',
    '123-index=2 type=file path=/owned projects/key=value current=yes',
    '123 index=3 type=db path=blah blah blah current=no',
)


class Stream:
    def __init__(self, chunks):
        self.chunks = list(chunks); self.sent = []; self.closed = False
    def settimeout(self, timeout): pass
    def sendall(self, value): self.sent.append(value)
    def recv(self, count):
        item = self.chunks.pop(0) if self.chunks else b''
        if isinstance(item, BaseException): raise item
        return item
    def close(self): self.closed = True


class RepositoryTests(unittest.TestCase):
    def test_exact_order_paths_response_and_detached_immutable_result(self):
        raw = response(*LITERAL); value = parse_repository_list(raw)
        self.assertEqual(value.current_indices, (2,)); self.assertEqual(value.current_index, 2)
        self.assertEqual(value.current_state, 'unique')
        self.assertEqual([item.type for item in value.repositories], ['sqlite-file', 'file', 'db'])
        self.assertEqual(value.repositories[1].path, '/owned projects/key=value')
        self.assertIs(value.response, raw)
        with self.assertRaises(FrozenInstanceError): value.repositories[0].path = 'changed'
        exported = value.as_dict(); exported['repositories'][0]['path'] = 'changed'
        exported['native_response']['lines'].clear()
        self.assertEqual(value.repositories[0].path, '/owned projects/key=value')
        self.assertEqual(value.response.lines, LITERAL)
        self.assertTrue(value.as_dict()['read_only']); self.assertFalse(value.as_dict()['repository_changed'])

    def test_unknown_multiple_and_empty_never_infer_current_index(self):
        for lines, state, indices in ((tuple(s.replace('current=yes', 'current=no') for s in LITERAL), 'unknown', []),
                                      (tuple(s.replace('current=no', 'current=yes') for s in LITERAL), 'multiple', [1,2,3]),
                                      (('124 no repositories found',), 'unknown', [])):
            with self.subTest(state=state, lines=lines):
                value = parse_repository_list(response(*lines)).as_dict()
                self.assertEqual(value['current_state'], state); self.assertEqual(value['current_indices'], indices)
                self.assertIsNone(value['current_index'])
        self.assertEqual(parse_repository_list(response('124 no repositories found')).repositories, ())

    def test_flag_like_path_suffixes_spaces_equals_unicode_and_empty_path_preserved(self):
        for path in (' leading and trailing ', r'C:\Owned Projects\x=y', '/é/日本語',
                     '/a current=yes path=x type=db current=no', '', '=', 'current=yes'):
            with self.subTest(path=path):
                raw = response(f'123 index=1 type=file path={path} current=no')
                self.assertEqual(parse_repository_list(raw).repositories[0].path, path)

    def test_bad_markers_numbers_suffixes_and_statuses_rejected(self):
        cases = [
            ('200 OK.',), ('124-No repositories found',), ('124 no repositories found ',),
            ('123-index=1 type=file path=/a current=yes',),
            ('123 index=2 type=file path=/a current=yes',),
            ('123 index=01 type=file path=/a current=yes',),
            ('123 index=0 type=file path=/a current=yes',),
            ('123 index=999999999999999999999 type=file path=/a current=yes',),
            ('123 index=1 type=file path=/a current=true',),
            ('123 index=1 type=file path=/a current=yes ',),
            ('123 index=1 type=file path=/a\nother current=yes',),
            ('123 index=1 type=file path=/a\x00 current=yes',),
            ('123 index=1 type=file path=/a\ud800 current=yes',),
            ('123 index=1 type= path=/a current=yes',),
            ('123 index=1 type=file path=/a current=yes', '123 index=2 type=file path=/b current=no'),
            ('123-index=1 type=file path=/a current=yes', '123 index=1 type=file path=/b current=no'),
            ('123-index=1 type=file path=/a current=yes', '124 no repositories found'),
            ('123-index=1 type=file path=/a current=yes', '200 OK.'),
        ]
        for lines in cases:
            with self.subTest(lines=lines), self.assertRaises(ValueError): parse_repository_list(response(*lines))

    def test_invalid_response_shapes_and_bounded_size_rejected(self):
        good = response(*LITERAL)
        cases = [None, {}, replace(good, lines=list(good.lines)), replace(good, lines=()),
                 replace(good, final='123 another final'), replace(good, status=True),
                 replace(good, status=200), replace(good, lines=(1,)),
                 response('123 index=1 type=file path=' + 'x' * (4*1024*1024) + ' current=yes'),
                 CGateResponse(('x',)*4097, 'x', 123)]
        for raw in cases:
            with self.subTest(type=type(raw).__name__), self.assertRaises(ValueError): parse_repository_list(raw)
        for fields in ((True,'file','x',False),(1,'file','x',1),(1,'bad type','x',False),(1,'file',None,False)):
            with self.assertRaises(ValueError): RepositoryDescriptor(*fields)

    def test_fragmented_real_client_continuations_and_events_use_one_list(self):
        wire = ('201 Service ready\r\n#e# owned event\r\n' + '\r\n'.join('[1] '+line for line in LITERAL) + '\r\n').encode()
        stream = Stream([wire[i:i+7] for i in range(0,len(wire),7)])
        with patch('cbus_toolkit.cgate.socket.create_connection', return_value=stream):
            with CGateClient('127.0.0.1',12345) as client:
                value = NativeRepositories(client).list()
                self.assertEqual(value.current_index,2); self.assertEqual(list(client.events), ['#e# owned event'])
        self.assertEqual(stream.sent,[b'[1] REPOSITORY LIST\r\n']); self.assertTrue(stream.closed)

    def test_rejection_missing_final_wrong_tag_and_interrupt_do_not_retry(self):
        for chunks, kind in (([b'[1] 400 Syntax Error\r\n'],CGateError),
                             ([b'[1] 123-index=1 type=file path=x current=yes\r\n'],RuntimeError),
                             ([b'[2] 123 index=1 type=file path=x current=yes\r\n'],RuntimeError),
                             ([KeyboardInterrupt('stop')],KeyboardInterrupt)):
            with self.subTest(kind=kind):
                stream=Stream([b'201 Ready\r\n',*chunks])
                with patch('cbus_toolkit.cgate.socket.create_connection',return_value=stream):
                    with self.assertRaises(kind) as caught:
                        with CGateClient('127.0.0.1',12345) as client: NativeRepositories(client).list()
                if kind is KeyboardInterrupt: self.assertIs(caught.exception,chunks[0])
                self.assertEqual(stream.sent,[b'[1] REPOSITORY LIST\r\n']); self.assertTrue(stream.closed)


@unittest.skipUnless(os.environ.get('CBUS_CGATE_JAVA') and os.environ.get('CBUS_LOCAL_CGATE_VENDOR'),
                     'Select Java11 and vendor for an owned local repository differential')
class NativeRepositoryTests(unittest.TestCase):
    def test_original_listing_and_cli_preserve_owned_path_and_empty_projects(self):
        from research.local_cgate import LocalCGate
        service=LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
        evidence={'passed':False,'service':service.report,'physical_networks_opened':False,'repository_selection_requested':False}
        try:
            projects=service.work/'owned projects = fixture'; projects.mkdir()
            config=service.work/'config/C-GateConfig.txt'
            config.write_text(config.read_text()+f'project.default.dir={projects}\n')
            (service.work/'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
            service.start()
            with CGateClient('127.0.0.1',service.port,timeout=10) as client:
                before=client.command('PROJECT LIST')
                calls=[]; original=client.command
                def record(text):
                    raw=original(text); calls.append((text,raw)); return raw
                client.command=record
                result=NativeRepositories(client).list()
                self.assertEqual([c[0] for c in calls],['REPOSITORY LIST'])
                self.assertEqual([r.type for r in result.repositories],['sqlite-file','file','db'])
                self.assertEqual([r.path for r in result.repositories],[str(projects),str(projects),'blah blah blah'])
                self.assertEqual(result.response,calls[0][1])
                self.assertEqual(before.lines,('124 no projects found',))
                after=original('PROJECT LIST'); self.assertEqual(after,before)
                evidence['api']=result.as_dict()
            process=subprocess.run([sys.executable,'-m','cbus_toolkit','cgate','--host','127.0.0.1',
                                    '--port',str(service.port),'repositories'],capture_output=True,text=True,timeout=20)
            self.assertEqual(process.returncode,0,process.stdout+process.stderr)
            cli=json.loads(process.stdout)
            self.assertEqual([r['path'] for r in cli['repositories']],[str(projects),str(projects),'blah blah blah'])
            self.assertEqual(cli['native_response']['code'],123)
            self.assertEqual(list(projects.iterdir()),[])
            evidence['cli']=cli; evidence['passed']=True
        finally:
            try: service.close()
            finally:
                evidence['passed'] = evidence['passed'] and service.report['cleanup_complete']
                output=os.environ.get('CBUS_REPOSITORIES_NATIVE_REPORT')
                if output: Path(output).write_text(json.dumps(evidence,indent=2)+'\n')
        self.assertTrue(service.report['cleanup_complete'])
        self.assertFalse(service.work.exists())
