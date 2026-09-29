"""Verified download of one catalogue-bound SESU package file; never installs.

The URL, size and SHA-1 all come from one exact raw catalogue response that
must reproduce a supplied ``update-catalogue`` report. Those catalogue claims
remain untrusted: a successful download proves only that the received bytes
match the selected descriptor over a certificate- and hostname-verified TLS
connection. Nothing downloaded here is executed, opened or installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import urllib.parse

from .toolkit_update_bundle import _complete_http_receipt, _parse, _same_json, _source
from .toolkit_update_metadata import MAX_NODE_BYTES, _json
from .toolkit_update_package_file import (
    MAX_PACKAGE_BYTES,
    inspect_update_package_file,
    select_package_descriptor,
)
from .toolkit_updates import CATALOGUE_URL, UpdateFailure, _candidate, _timeout, catalogue_request


FORMAT = "cbus-toolkit-update-download-v1"
MAX_REDIRECTS = 5
MAX_CA_BYTES = 1024 * 1024
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._()+ -]{0,199}\Z", re.ASCII)
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?\Z", re.IGNORECASE)
_IS_WINDOWS = os.name == "nt"


class UpdateDownloadError(ValueError):
    """The inputs cannot bind a download; no network request was made."""


class _Failure(Exception):
    def __init__(self, stage, kind, message):
        super().__init__(message)
        self.stage, self.kind = stage, kind


def _false(value, name):
    if value is not False:
        raise UpdateDownloadError(f"catalogue report must keep {name} false")


@dataclass(frozen=True)
class DownloadSource:
    url: str
    host: str
    port: int
    file_name: str
    node_id: str
    file_id: str
    declared_size: int
    declared_sha1: str
    provenance: dict = field(compare=False)


def _safe_file_name(url_path: str) -> str:
    name = urllib.parse.unquote(url_path.rsplit("/", 1)[-1], errors="strict")
    if (
        _FILE_NAME.fullmatch(name) is None
        or name.endswith((".", " "))
        or _RESERVED.match(name)
        or ".." in name
    ):
        raise UpdateDownloadError("catalogue URL does not end in a safe plain file name")
    return name


def _https_url(url: str):
    if (
        type(url) is not str
        or not url.isascii()
        or any(ord(character) <= 0x20 or ord(character) == 0x7F for character in url)
    ):
        raise UpdateDownloadError("URL must be printable ASCII without whitespace")
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port or 443
    except ValueError as error:
        raise UpdateDownloadError("URL has an invalid port") from error
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or not parts.path.startswith("/")
    ):
        raise UpdateDownloadError("only an absolute https URL without credentials or fragment is supported")
    target = parts.path + ("?" + parts.query if parts.query else "")
    return parts.hostname.lower(), port, target, parts.path


def bind_download_source(
    catalogue_report: bytes,
    catalogue_response: bytes,
    *,
    node_id: str,
    file_id: str,
    max_package_bytes: int = MAX_PACKAGE_BYTES,
) -> DownloadSource:
    """Bind one file URL to a complete catalogue report and its exact response.

    The report must reproduce from the response with the same checks as the
    diagnostic bundle's catalogue link. Any unbound, ambiguous or unsafe
    input raises before a network connection is attempted.
    """
    report = _parse(catalogue_report, "catalogue")
    response = _source(catalogue_response, "catalogue_response", MAX_NODE_BYTES)
    if report.get("complete") is not True or "error" not in report or report["error"] is not None:
        raise UpdateDownloadError("catalogue report must be a complete error-free query")
    for name in ("metadata_signature_verified", "applicability_verified", "downloaded", "installed"):
        _false(report.get(name), name)
    if report.get("updates_available") is not None:
        raise UpdateDownloadError("catalogue report must not claim update availability")
    http = report.get("http")
    body_sha256 = hashlib.sha256(catalogue_response).hexdigest()
    if (
        type(http) is not dict
        or not _complete_http_receipt(http, catalogue_response)
        or http.get("body_sha256") != body_sha256
    ):
        raise UpdateDownloadError("catalogue HTTP receipt does not describe the exact response bytes")
    installed_version = report.get("installed_version")
    try:
        request_sha256 = hashlib.sha256(catalogue_request(installed_version)).hexdigest()
    except ValueError as error:
        raise UpdateDownloadError("catalogue report has an invalid installed version") from error
    if report.get("endpoint") != CATALOGUE_URL or report.get("request_sha256") != request_sha256:
        raise UpdateDownloadError("catalogue report endpoint or request receipt does not match")
    message = response.get("message")
    if not (
        response.get("success") is True
        and type(response.get("statusCode")) is int and response["statusCode"] == 200
        and report.get("body_success") is True
        and type(report.get("body_status")) is int and report["body_status"] == 200
        and type(message) is str and report.get("body_message") == message
    ):
        raise UpdateDownloadError("catalogue body status does not match the exact response")
    nodes = response.get("data")
    if type(nodes) is not list or len(nodes) > 256 or any(type(node) is not dict for node in nodes):
        raise UpdateDownloadError("catalogue response data must be a bounded node array")
    candidates = [_candidate(node).as_dict() for node in nodes]
    if len({item["node_id"] for item in candidates}) != len(candidates):
        raise UpdateDownloadError("catalogue response contains an ambiguous repeated node_id")
    if not _same_json(candidates, report.get("candidates")):
        raise UpdateDownloadError("catalogue report candidates do not reproduce from the response")

    selected, canonical, size, sha1 = select_package_descriptor(
        catalogue_response, node_id=node_id, file_id=file_id,
        max_package_bytes=max_package_bytes,
    )
    files = [item for item in _json(selected)["files"] if item.get("id") == file_id]
    url = files[0].get("url")
    host, port, _, path = _https_url(url)
    return DownloadSource(
        url=url, host=host, port=port, file_name=_safe_file_name(path),
        node_id=node_id, file_id=file_id, declared_size=size, declared_sha1=sha1,
        provenance={
            "catalogue_report_sha256": hashlib.sha256(catalogue_report).hexdigest(),
            "catalogue_response_sha256": body_sha256,
            "catalogue_endpoint": CATALOGUE_URL,
            "installed_version": installed_version,
            "request_sha256": request_sha256,
            "selected_node_sha256": hashlib.sha256(selected).hexdigest(),
            "canonical_node_sha256": hashlib.sha256(canonical).hexdigest(),
            "url_bound_to_catalogue_report": True,
        },
    )


def tls_context(ca_bytes: bytes | None = None) -> ssl.SSLContext:
    """System trust, or only the exact supplied CA bytes; never unverified."""
    if ca_bytes is None:
        context = ssl.create_default_context()
    else:
        try:
            context = ssl.create_default_context(cadata=ca_bytes.decode("ascii"))
        except UnicodeDecodeError:
            context = ssl.create_default_context(cadata=ca_bytes)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise UpdateDownloadError("TLS context must require certificate and hostname verification")
    return context


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _publish(directory: Path, source: str, target: str):
    """Move without replacing an existing name; the source is left on failure."""
    if _IS_WINDOWS:
        os.rename(directory / source, directory / target)  # Refuses an existing target.
    else:
        os.link(directory / source, directory / target, follow_symlinks=False)
        os.unlink(directory / source)


def _write_exclusive(path: Path, data: bytes):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) \
        | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def download_update_package(
    catalogue_report: bytes,
    catalogue_response: bytes,
    *,
    node_id: str,
    file_id: str,
    output_dir: str | os.PathLike[str],
    ca_bytes: bytes | None = None,
    timeout: float = 60,
    max_package_bytes: int = MAX_PACKAGE_BYTES,
) -> dict:
    """Download one bound file into a new name in ``output_dir``.

    Returns the report dictionary. Invalid inputs, an unsafe output directory
    and an already-existing output name raise before any network access.
    Network, size, digest and publication failures return an unsuccessful
    report and leave a ``*.failed.json`` record plus any received bytes as a
    ``*.failed.partial`` artifact. Interruptions retain the same artifacts.
    """
    timeout = _timeout(timeout)
    if ca_bytes is not None and (type(ca_bytes) is not bytes or not 0 < len(ca_bytes) <= MAX_CA_BYTES):
        raise UpdateDownloadError("CA file must be nonempty and within 1 MiB")
    source = bind_download_source(
        catalogue_report, catalogue_response, node_id=node_id, file_id=file_id,
        max_package_bytes=max_package_bytes,
    )
    directory = Path(output_dir)
    status = directory.lstat()
    if not stat.S_ISDIR(status.st_mode):
        raise UpdateDownloadError("output must be an existing directory, not a link")
    try:
        (directory / source.file_name).lstat()
    except FileNotFoundError:
        pass
    else:
        raise UpdateDownloadError("output file already exists; it is never overwritten")
    context = tls_context(ca_bytes)

    token = _now() + "-" + secrets.token_hex(6)
    temporary = "." + source.file_name + "." + token + ".download"
    failed_partial = source.file_name + "." + token + ".failed.partial"
    failed_record = source.file_name + "." + token + ".failed.json"
    report = {
        "format": FORMAT,
        "scope": "One catalogue-bound package file downloaded over verified TLS; not installed or executed",
        "outcome": "failed",
        "provenance": dict(source.provenance, node_id=node_id, file_id=file_id, url=source.url),
        "tls": {
            "trust": "explicit_ca_file" if ca_bytes is not None else "system_default",
            "ca_file_sha256": hashlib.sha256(ca_bytes).hexdigest() if ca_bytes is not None else None,
            "certificate_verified": None, "hostname_checked": True,
            "protocol": None, "cipher": None, "peer_certificate_sha256": None,
        },
        "http": {"requests": [], "redirect_policy": "same-origin https only, at most 5",
                 "proxy_used": False, "retries": 0, "end_to_end_deadline_bounded": False},
        "declared_size": source.declared_size,
        "declared_sha1": source.declared_sha1,
        "max_package_bytes": max_package_bytes,
        "bytes_received": 0,
        "observed_sha1": None,
        "observed_sha256": None,
        "package_receipt": None,
        "output_file_name": None,
        "failure": None,
        "failure_artifacts": None,
        "cleanup": [],
        "catalogue_claims_trusted": False,
        "metadata_signature_verified": False,
        "publisher_trust_evaluated": False,
        "package_applicability_evaluated": False,
        "install_permitted": False,
        "executed": False,
        "installed": False,
    }
    descriptor = None
    created = False
    connection = response = None
    sha1 = hashlib.sha1(usedforsecurity=False)  # Legacy catalogue field, not trust.
    sha256 = hashlib.sha256()
    interruption = None

    def close_network():
        nonlocal connection, response
        for name, resource in (("response", response), ("connection", connection)):
            if resource is None:
                continue
            try:
                resource.close()
                report["cleanup"].append({"resource": name, "succeeded": True, "error": None})
            except Exception as error:
                report["cleanup"].append({"resource": name, "succeeded": False,
                                          "error": UpdateFailure.from_error(name + "_close", error).as_dict()})
        connection = response = None

    stage = "connect"
    try:
        host, port, target = source.host, source.port, _https_url(source.url)[2]
        for hop in range(MAX_REDIRECTS + 1):
            stage = "connect"
            connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
            try:
                connection.connect()
            except ssl.SSLCertVerificationError as error:
                report["tls"]["certificate_verified"] = False
                raise _Failure("tls", "CertificateVerificationFailed", str(error)) from error
            except ssl.SSLError as error:
                raise _Failure("tls", type(error).__name__, str(error)) from error
            tls = connection.sock
            report["tls"].update(certificate_verified=True, protocol=tls.version(),
                                 cipher=(tls.cipher() or (None,))[0],
                                 peer_certificate_sha256=hashlib.sha256(
                                     tls.getpeercert(binary_form=True) or b"").hexdigest())
            stage = "request"
            connection.request("GET", target, headers={
                "Accept": "*/*", "Accept-Encoding": "identity",
                "User-Agent": "cbus-toolkit-update-download"})
            stage = "response_headers"
            response = connection.getresponse()
            headers = response.getheaders()
            report["http"]["requests"].append({"host": host, "port": port, "target": target,
                                               "status": response.status})
            if response.status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise _Failure("redirect", "MissingLocation", "redirect without Location")
                resolved = urllib.parse.urljoin(f"https://{host}:{port}{target}", location)
                report["http"]["requests"][-1]["location"] = resolved
                try:
                    next_host, next_port, next_target, _ = _https_url(resolved)
                except UpdateDownloadError as error:
                    raise _Failure("redirect", "UnsupportedRedirect", str(error)) from error
                if (next_host, next_port) != (source.host, source.port):
                    raise _Failure("redirect", "CrossOriginRedirectRefused",
                                   "redirect to another origin is refused")
                if hop == MAX_REDIRECTS:
                    raise _Failure("redirect", "TooManyRedirects", "redirect limit exceeded")
                close_network()
                host, port, target = next_host, next_port, next_target
                continue
            break
        if response.status != 200:
            raise _Failure("http_status", "UnexpectedStatus", f"HTTP status {response.status}")
        values = lambda name: [value for key, value in headers if key.lower() == name]
        lengths, encodings, transfers = values("content-length"), values("content-encoding"), values("transfer-encoding")
        if len(lengths) > 1 or (lengths and transfers):
            raise _Failure("response_headers", "AmbiguousFraming", "ambiguous HTTP response framing")
        if encodings and (len(encodings) != 1 or encodings[0].strip().lower() != "identity"):
            raise _Failure("response_headers", "EncodedResponse", "encoded responses are unsupported")
        if transfers and (len(transfers) != 1 or transfers[0].strip().lower() != "chunked"):
            raise _Failure("response_headers", "UnsupportedTransferEncoding", "unsupported transfer encoding")
        if lengths:
            if not lengths[0].isascii() or not lengths[0].isdigit():
                raise _Failure("response_headers", "InvalidContentLength", "invalid Content-Length")
            declared = int(lengths[0])
            report["http"]["content_length"] = declared
            if declared > source.declared_size:
                raise _Failure("response_headers", "Oversize", "Content-Length exceeds the catalogue size")
            if declared != source.declared_size:
                raise _Failure("response_headers", "ContentLengthMismatch",
                               "Content-Length differs from the catalogue size")

        stage = "create_temporary"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) \
            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
        descriptor = os.open(directory / temporary, flags, 0o600)
        created = True

        def keep(block):
            view = memoryview(block)
            while view:
                view = view[os.write(descriptor, view):]
            sha1.update(block)
            sha256.update(block)
            report["bytes_received"] += len(block)

        stage = "response_body"
        while True:
            remaining = source.declared_size - report["bytes_received"]
            try:
                block = response.read(min(1024 * 1024, remaining + 1))
            except http.client.IncompleteRead as error:
                keep(error.partial[:remaining])
                raise _Failure("response_body", "Truncated", "connection ended before the declared size") from error
            if not block:
                break
            if len(block) > remaining:
                keep(block[:remaining])
                raise _Failure("response_body", "Oversize", "response exceeds the catalogue size")
            keep(block)
        if report["bytes_received"] != source.declared_size:
            raise _Failure("response_body", "Truncated", "response ended before the declared size")
        close_network()
        if any(not item["succeeded"] for item in report["cleanup"]):
            raise _Failure("connection_close", "CleanupFailed", "network cleanup failed")
        stage = "verify"
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        report["observed_sha1"] = sha1.hexdigest()
        report["observed_sha256"] = sha256.hexdigest()
        if report["observed_sha1"] != source.declared_sha1:
            raise _Failure("verify", "HashMismatch", "received bytes do not match the catalogue SHA-1")
        receipt = inspect_update_package_file(
            catalogue_response, node_id=node_id, file_id=file_id,
            package_path=directory / temporary, max_package_bytes=max_package_bytes,
        ).as_dict()
        report["package_receipt"] = receipt
        if not receipt["bytes_match_catalogue_descriptor"] or receipt["observed_sha256"] != report["observed_sha256"]:
            raise _Failure("verify", "ReceiptMismatch", "re-read file does not reproduce the streamed digest")
        stage = "publish"
        try:
            _publish(directory, temporary, source.file_name)
        except FileExistsError as error:
            raise _Failure("publish", "OutputExists", "output name appeared during download; not overwritten") from error
        created = False
        report["outcome"] = "downloaded"
        report["output_file_name"] = source.file_name
        return report
    except _Failure as error:
        report["failure"] = {"stage": error.stage, "type": error.kind, "message": str(error)[:4096]}
    except Exception as error:
        report["failure"] = UpdateFailure.from_error(stage, error).as_dict()
    except BaseException as error:
        report["failure"] = UpdateFailure.from_error(stage, error).as_dict()
        interruption = error
    finally:
        if report["outcome"] != "downloaded":
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            close_network()
            artifacts = {"record": failed_record, "partial": None, "partial_bytes": report["bytes_received"]}
            report["failure_artifacts"] = artifacts
            if created:
                try:
                    _publish(directory, temporary, failed_partial)
                    artifacts["partial"] = failed_partial
                except OSError as error:
                    artifacts["partial"] = temporary
                    artifacts["partial_rename_error"] = UpdateFailure.from_error("retain_partial", error).as_dict()
            if report["observed_sha256"] is None and created:
                report["observed_sha1"] = sha1.hexdigest()
                report["observed_sha256"] = sha256.hexdigest()
            try:
                _write_exclusive(directory / failed_record,
                                 json.dumps(report, indent=2, ensure_ascii=True).encode("ascii") + b"\n")
            except OSError as error:
                artifacts["record"] = None
                artifacts["record_error"] = UpdateFailure.from_error("failure_record", error).as_dict()
    if interruption is not None:
        try:
            interruption.toolkit_update_evidence = report
        except BaseException:
            pass
        raise interruption
    return report
