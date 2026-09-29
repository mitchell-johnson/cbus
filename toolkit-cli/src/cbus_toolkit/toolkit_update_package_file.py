"""Offline byte-to-catalogue receipt for one SESU package file.

This deliberately does not decide publisher trust or installation permission.
The SHA-1 and size are untrusted catalogue claims until the complete metadata
trust policy has been evaluated, and SHA-1 alone is not a modern authenticity
primitive. No catalogue URL is followed and no package is executed.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import stat
from pathlib import Path

from .toolkit_update_metadata import (
    MAX_NODE_BYTES,
    _canonical,
    _json,
    select_node,
    validate_node_id,
)
from .toolkit_updates import _candidate


MAX_PACKAGE_BYTES = (1 << 31) - 1
_SHA1 = re.compile(r"[0-9a-fA-F]{40}\Z", re.ASCII)
_IS_WINDOWS = os.name == "nt"


@dataclass(frozen=True)
class UpdatePackageFileReceipt:
    catalogue_source_sha256: str
    selected_node_sha256: str
    canonical_node_sha256: str
    node_id: str
    file_id: str
    declared_size: int
    declared_sha1: str
    observed_size: int
    observed_sha1: str
    observed_sha256: str

    @property
    def bytes_match_catalogue_descriptor(self) -> bool:
        return (
            self.observed_size == self.declared_size
            and self.observed_sha1 == self.declared_sha1
        )

    def as_dict(self) -> dict:
        return {
            "format": "cbus-toolkit-update-package-file-receipt-v1",
            "scope": "Local regular-file bytes against one untrusted catalogue descriptor",
            "catalogue_source_sha256": self.catalogue_source_sha256,
            "selected_node_sha256": self.selected_node_sha256,
            "canonical_node_sha256": self.canonical_node_sha256,
            "node_id": self.node_id,
            "file_id": self.file_id,
            "declared_size": self.declared_size,
            "declared_sha1": self.declared_sha1,
            "observed_size": self.observed_size,
            "observed_sha1": self.observed_sha1,
            "observed_sha256": self.observed_sha256,
            "bytes_match_catalogue_descriptor": self.bytes_match_catalogue_descriptor,
            "metadata_signature_verified": False,
            "publisher_trust_evaluated": False,
            "complete_revocation_status_evaluated": False,
            "package_applicability_evaluated": False,
            "install_permitted": False,
            "downloaded": False,
            "installed": False,
        }


def select_package_descriptor(
    catalogue_response: bytes,
    *,
    node_id: str,
    file_id: str,
    max_package_bytes: int = MAX_PACKAGE_BYTES,
) -> tuple[bytes, bytes, int, str]:
    """Select one exact raw-catalogue file descriptor without reading a package.

    Returns the normalized selected node, its canonical metadata bytes, the
    declared size and the lowercase declared SHA-1. Both claims remain untrusted.
    """
    validate_node_id(node_id)
    if type(file_id) is not str or not 0 < len(file_id) <= 256 or "\0" in file_id:
        raise ValueError("file_id must be bounded nonempty text without NUL")
    if type(max_package_bytes) is not int or not 0 < max_package_bytes <= MAX_PACKAGE_BYTES:
        raise ValueError("max_package_bytes must be a positive signed Int32 bound")
    response = _json(catalogue_response, limit=MAX_NODE_BYTES)
    if (
        type(response) is not dict
        or response.get("success") is not True
        or type(response.get("statusCode")) is not int
        or response["statusCode"] != 200
    ):
        raise ValueError("catalogue response must report exact success and statusCode 200")
    selected = select_node(catalogue_response, node_id=node_id)
    node = _json(selected)
    _candidate(node)  # Reject ambiguous IDs and malformed public file descriptors.
    canonical = _canonical(node)
    canonical_node = _json(canonical)
    files = canonical_node.get("files")
    if type(files) is not list or any(type(item) is not dict for item in files):
        raise ValueError("selected metadata node has no complete file list")
    matches = [item for item in files if item.get("id") == file_id]
    if len(matches) != 1:
        raise ValueError("expected exactly one selected file_id in the metadata node")
    descriptor = matches[0]
    size = descriptor.get("size")
    if type(size) is not int or not 0 <= size <= max_package_bytes:
        raise ValueError("declared package size exceeds the bounded file profile")
    security = descriptor.get("security")
    sha1 = security.get("sha1") if type(security) is dict else None
    if type(sha1) is not str or _SHA1.fullmatch(sha1) is None:
        raise ValueError("selected file has no exact 40-digit security.sha1")
    return selected, canonical, size, sha1.lower()


def inspect_update_package_file(
    catalogue_response: bytes,
    *,
    node_id: str,
    file_id: str,
    package_path: str | os.PathLike[str],
    max_package_bytes: int = MAX_PACKAGE_BYTES,
) -> UpdatePackageFileReceipt:
    """Read one local file and compare it with its exact raw-catalogue entry.

    A malformed, ambiguous, missing-security or unsafe-file input raises.
    A complete read with a wrong size or digest returns a negative receipt.
    The selected node is canonicalized with the same bounded model as the
    existing metadata diagnostic, but its JWT is not verified here.
    """
    selected, canonical, size, sha1 = select_package_descriptor(
        catalogue_response, node_id=node_id, file_id=file_id,
        max_package_bytes=max_package_bytes,
    )

    path = os.fspath(package_path)
    if type(path) is not str or not path or "\0" in path:
        raise ValueError("package_path must be nonempty filesystem text without NUL")
    if _IS_WINDOWS:
        observed, observed_sha1, observed_sha256 = _hash_windows_regular_file(
            path, max_package_bytes
        )
    else:
        observed, observed_sha1, observed_sha256 = _hash_posix_regular_file(
            Path(path), max_package_bytes
        )
    return UpdatePackageFileReceipt(
        catalogue_source_sha256=hashlib.sha256(catalogue_response).hexdigest(),
        selected_node_sha256=hashlib.sha256(selected).hexdigest(),
        canonical_node_sha256=hashlib.sha256(canonical).hexdigest(),
        node_id=node_id,
        file_id=file_id,
        declared_size=size,
        declared_sha1=sha1,
        observed_size=observed,
        observed_sha1=observed_sha1,
        observed_sha256=observed_sha256,
    )


def _hash_posix_regular_file(path: Path, max_package_bytes: int) -> tuple[int, str, str]:
    # Refuse POSIX-like platforms lacking a race-resistant no-follow open.
    required = ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
    if any(not hasattr(os, flag) for flag in required):
        raise OSError("safe package-file open is unavailable on this platform")
    prior = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(prior.st_mode) or prior.st_size > max_package_bytes:
        raise ValueError("package must be a bounded regular file")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        identity = lambda item: (
            item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns
        )
        if not stat.S_ISREG(before.st_mode) or identity(prior) != identity(before):
            raise ValueError("package changed before the file read")
        observed = 0
        sha1_hash = hashlib.sha1(usedforsecurity=False)  # Legacy catalogue field, not trust.
        sha256_hash = hashlib.sha256()
        while True:
            block = os.read(fd, min(1024 * 1024, max_package_bytes - observed + 1))
            if not block:
                break
            observed += len(block)
            if observed > max_package_bytes:
                raise ValueError("package exceeds max_package_bytes during read")
            sha1_hash.update(block)
            sha256_hash.update(block)
        after = os.fstat(fd)
        if observed != before.st_size or identity(before) != identity(after):
            raise ValueError("package changed during the file read")
    finally:
        os.close(fd)
    return observed, sha1_hash.hexdigest(), sha256_hash.hexdigest()


def _hash_windows_regular_file(path: str, max_package_bytes: int) -> tuple[int, str, str]:
    """Hash one Win32 disk-file handle without following its final reparse point.

    A read-only handle with only FILE_SHARE_READ denies concurrent writers and
    renames/deletes while it is open. Unsupported file-information queries fail
    closed; unsupported Windows/filesystem handle queries are rejected.
    """
    import ctypes
    from ctypes import wintypes
    import msvcrt

    file_attribute_reparse_point = 0x400
    prior = os.stat(path, follow_symlinks=False)
    if (
        not stat.S_ISREG(prior.st_mode)
        or prior.st_size > max_package_bytes
        or getattr(prior, "st_file_attributes", 0) & file_attribute_reparse_point
    ):
        raise ValueError("package must be a bounded regular non-reparse file")

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

    class FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation_time", ctypes.c_int64),
            ("last_access_time", ctypes.c_int64),
            ("last_write_time", ctypes.c_int64),
            ("change_time", ctypes.c_int64),
            ("attributes", wintypes.DWORD),
        ]

    class FileStandardInfo(ctypes.Structure):
        _fields_ = [
            ("allocation_size", ctypes.c_int64),
            ("end_of_file", ctypes.c_int64),
            ("number_of_links", wintypes.DWORD),
            ("delete_pending", ctypes.c_ubyte),
            ("directory", ctypes.c_ubyte),
        ]

    class FileIdInfo(ctypes.Structure):
        _fields_ = [
            ("volume_serial_number", ctypes.c_uint64),
            ("file_id", ctypes.c_ubyte * 16),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_file_type = kernel32.GetFileType
    get_file_type.argtypes = [wintypes.HANDLE]
    get_file_type.restype = wintypes.DWORD
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    read_file = kernel32.ReadFile
    read_file.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    read_file.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    # NULL security attributes make the handle non-inheritable. Share-read-only
    # prevents new write/delete opens and fails if an incompatible writer exists.
    handle = create_file(path, 0x80000000, 0x00000001, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    fd = None
    try:
        # The CRT descriptor owns the exact CreateFileW handle from here on;
        # fstat binds it to the pre-open Python path identity.
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        if get_file_type(handle) != 1:  # FILE_TYPE_DISK
            raise ValueError("package handle is not a disk file")

        def query(info_class: int, info_type: type[ctypes.Structure]) -> ctypes.Structure:
            info = info_type()
            if not get_info(handle, info_class, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            return info

        def snapshot() -> tuple[int, int, int, int, int, int, int, bytes]:
            tag = query(9, FileAttributeTagInfo)
            standard = query(1, FileStandardInfo)
            basic = query(0, FileBasicInfo)
            file_id = query(18, FileIdInfo)
            if tag.attributes & file_attribute_reparse_point or tag.reparse_tag:
                raise ValueError("package handle is a reparse point")
            if tag.attributes & 0x10 or standard.directory or standard.delete_pending:
                raise ValueError("package handle is not a regular file")
            if standard.end_of_file < 0 or standard.end_of_file > max_package_bytes:
                raise ValueError("package exceeds max_package_bytes")
            return (
                standard.end_of_file, standard.number_of_links,
                basic.last_write_time, basic.change_time, basic.attributes,
                file_id.volume_serial_number, tag.attributes, bytes(file_id.file_id),
            )

        before = snapshot()
        opened_handle = os.fstat(fd)
        opened_path = os.stat(path, follow_symlinks=False)
        path_identity = lambda item: (
            item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns
        )
        if (
            not prior.st_ino
            or before[0] != prior.st_size
            or path_identity(prior) != path_identity(opened_handle)
            or path_identity(prior) != path_identity(opened_path)
        ):
            raise ValueError("package changed before the file read")
        observed = 0
        sha1_hash = hashlib.sha1(usedforsecurity=False)  # Legacy catalogue field, not trust.
        sha256_hash = hashlib.sha256()
        buffer = ctypes.create_string_buffer(1024 * 1024)
        read_count = wintypes.DWORD()
        while True:
            if not read_file(
                handle, buffer, min(len(buffer), max_package_bytes - observed + 1),
                ctypes.byref(read_count), None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if not read_count.value:
                break
            observed += read_count.value
            if observed > max_package_bytes:
                raise ValueError("package exceeds max_package_bytes during read")
            block = buffer.raw[:read_count.value]
            sha1_hash.update(block)
            sha256_hash.update(block)
        after = snapshot()
        final_handle = os.fstat(fd)
        final_path = os.stat(path, follow_symlinks=False)
        if (
            observed != before[0]
            or before != after
            or path_identity(opened_handle) != path_identity(final_handle)
            or path_identity(prior) != path_identity(final_path)
        ):
            raise ValueError("package changed during the file read")
        return observed, sha1_hash.hexdigest(), sha256_hash.hexdigest()
    finally:
        if fd is None:
            close_handle(handle)
        else:
            os.close(fd)
