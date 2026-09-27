"""Host-local advisory lease for cooperating selected-serial address writers.

This coordinates CLI processes that name the same endpoint on one host. It is
not a C-Bus lock and cannot exclude another computer, cmqttd, or a controller
that does not acquire this lease. The OS releases the lock after a process
crash; the commissioning journal still controls read-only recovery and never
authorizes replay.
"""
from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import stat
import tempfile


class EndpointLeaseBusy(RuntimeError):
    """A cooperating process already holds the selected endpoint lease."""


def _directory() -> Path:
    identity = str(os.getuid()) if hasattr(os, "getuid") else "current-user"
    path = Path(tempfile.gettempdir()) / ("cbus-toolkit-selected-serial-" + identity)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("Commissioning lease directory is not a directory")
    if os.name != "nt" and (
        info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise RuntimeError("Commissioning lease directory is not private to this user")
    return path


class EndpointLease:
    """Nonblocking OS lock held until an address attempt is fully recorded."""

    def __init__(self, host: str, port: int):
        if type(host) is not str or not host or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Commissioning lease requires a validated endpoint")
        key = hashlib.sha256((host + "\0" + str(port)).encode("utf-8")).hexdigest()
        self.path = _directory() / (key + ".lock")
        self._descriptor: int | None = None

    def __enter__(self) -> EndpointLease:
        if self._descriptor is not None:
            raise RuntimeError("Commissioning endpoint lease is already held by this instance")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        if os.name != "nt":
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and (
                info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077
            )):
                raise RuntimeError("Commissioning lease file is not a private regular file")
            if os.name == "nt":
                import msvcrt

                if info.st_size == 0:
                    os.write(descriptor, b"\0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise EndpointLeaseBusy("Another process is commissioning this endpoint") from error
                    raise
            else:
                import fcntl

                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    if error.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                        raise EndpointLeaseBusy("Another process is commissioning this endpoint") from error
                    raise
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor = descriptor
        return self

    def __exit__(self, error_type, _error, _traceback) -> bool:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return False
        cleanup_error = None
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except BaseException as error:
            cleanup_error = error
        finally:
            try:
                os.close(descriptor)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None and error_type is None:
            raise RuntimeError("Failed to release commissioning endpoint lease") from cleanup_error
        return False
