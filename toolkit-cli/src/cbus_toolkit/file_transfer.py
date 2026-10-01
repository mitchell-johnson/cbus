"""Explicit bounded upload to the selected C-Gate server's FILE namespace."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import stat

from .native import NativeProjects, _project, _token

MAX_UPLOAD_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class FileUpload:
    server_path: str
    source: Path
    project: str | None
    data: bytes

    @property
    def document(self):
        encoded = base64.b64encode(self.data).decode('ascii')
        return '\n'.join(encoded[i:i + 76] for i in range(0, len(encoded), 76)) or '\n'


def prepare_upload(server_path, source, *, project=None):
    """Consume one stable regular-file snapshot before connecting."""
    server_path = _token(server_path, 'server FILE path')
    if '%' in server_path and not re.fullmatch(r'%[A-Za-z0-9_]{1,8}%/(?:[^%]+)', server_path):
        raise ValueError('Use one explicit %PROJECT% FILE root or an ordinary relative path')
    relative = server_path.partition('%/')[2] if server_path.startswith('%') else server_path
    if (server_path.startswith(('/', '\\')) or relative.startswith('~') or '..' in server_path or ':' in server_path
            or any(c in server_path for c in ('"', '\\', '<', '>'))
            or any(part in ('', '.', '..') for part in server_path.split('/'))
            or len(server_path.encode('utf-8')) > 255):
        raise ValueError('Server FILE path must be a bounded relative path without traversal or quoting')
    project = _project(project) if project is not None else None
    source = Path(source)
    before = source.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_UPLOAD_BYTES:
        raise ValueError('Upload source must be a regular file of at most 4 MiB')
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(source, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_UPLOAD_BYTES
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('Upload source changed before its regular-file snapshot was opened')
        data = stream.read(MAX_UPLOAD_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (len(data) > MAX_UPLOAD_BYTES or len(data) != opened.st_size
            or (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError('Upload source changed while its bounded snapshot was read')
    return FileUpload(server_path, source, project, data)


def upload(plan, client):
    if plan.project is not None:
        NativeProjects(client).operation('use', plan.project)
    response = client.command_document('FILE UPLOAD ' + plan.server_path, plan.document)
    if response.code != 200:
        raise RuntimeError('FILE upload did not complete: ' + response.final)
    return dict(format='cbus-cgate-file-upload-v1', server_path=plan.server_path,
                source_file=str(plan.source), bytes=len(plan.data), sha256=sha256(plan.data).hexdigest(),
                upload_completed=True, response=response, project_save_requested=False,
                server_storage_policy='Selected server FILE semantics; cmqttd uses its virtual namespace')
