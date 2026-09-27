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

    # Refuse platforms lacking a race-resistant no-follow regular-file open.
    required = ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
    if any(not hasattr(os, flag) for flag in required):
        raise OSError("safe package-file open is unavailable on this platform")
    path = Path(package_path)
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
    return UpdatePackageFileReceipt(
        catalogue_source_sha256=hashlib.sha256(catalogue_response).hexdigest(),
        selected_node_sha256=hashlib.sha256(selected).hexdigest(),
        canonical_node_sha256=hashlib.sha256(canonical).hexdigest(),
        node_id=node_id,
        file_id=file_id,
        declared_size=size,
        declared_sha1=sha1.lower(),
        observed_size=observed,
        observed_sha1=sha1_hash.hexdigest(),
        observed_sha256=sha256_hash.hexdigest(),
    )
