"""Opt-in Cargo runner: execute byte-identical tests on the internal filesystem.

Never changes test arguments, TLS roots, trust policy or the original executable.
The supplied temporary parent must be an internal filesystem. Records stay private.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()

def main() -> int:
    original = Path(sys.argv[1]).resolve(strict=True)
    parent = Path(os.environ['CBUS_RUST_TEST_RUNNER_DIR']).resolve(strict=True)
    records = Path(os.environ['CBUS_RUST_TEST_RUNNER_RECORDS'])
    expected = digest(original)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='owned-rust-test-',dir=parent) as folder:
        executable = Path(folder)/original.name
        shutil.copyfile(original,executable)
        executable.chmod(0o500)
        if digest(original) != expected or digest(executable) != expected:
            raise RuntimeError('Executable changed while preparing local test copy')
        process = subprocess.Popen([str(executable),*sys.argv[2:]])
        try:
            status=process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            raise
        actual = digest(executable)
        row={'original':str(original),'executed':str(executable),
             'argv':[str(executable),*sys.argv[2:]],'cwd':os.getcwd(),
             'pid':process.pid,'exit':status,'sha256_before':expected,'sha256_after':actual,
             'bytes':executable.stat().st_size,'source_original_end_sha256':digest(original),
             'SSL_CERT_FILE_set':'SSL_CERT_FILE' in os.environ,'SSL_CERT_DIR_set':'SSL_CERT_DIR' in os.environ,
             'elapsed_seconds':round(time.monotonic()-started,3)}
        with records.open('a') as stream:
            stream.write(json.dumps(row,sort_keys=True)+'\n')
        if actual != expected:
            raise RuntimeError('Executed test copy changed')
        return status

if __name__=='__main__':
    raise SystemExit(main())
