"""Toolkit's download-page action and unverified SESU catalogue candidates.

Catalogue results are server-assigned metadata, not verified updates. This module
does not compare versions, verify vendor metadata signatures, evaluate local
conditions, follow returned links, open a browser, or download/install software.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import http.client
import json
import math
import ssl
from typing import Mapping, Protocol

from .toolkit_preferences_store import validate_values

CATALOGUE_HOST = 'sw.dad.se.com'
CATALOGUE_PATH = '/collections/PackageData/list'
CATALOGUE_URL = 'https://' + CATALOGUE_HOST + CATALOGUE_PATH
TOOLKIT_PRODUCT_ID = '435e4274-3bcf-4f3e-a67a-3008278c539c'


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}')
    return value


def _text(value, name, maximum=4096, *, empty=True):
    if type(value) is not str or len(value) > maximum or '\0' in value or (not empty and not value):
        raise ValueError(f'{name} must be {"a nonempty" if not empty else "a"} string of at most {maximum} characters without NUL')
    try:
        value.encode('utf-8')
    except UnicodeError as error:
        raise ValueError(f'{name} must be valid Unicode') from error
    return value


def _timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 300:
        raise ValueError('timeout must be finite, positive and at most 300 seconds per blocking operation')
    return float(value)


@dataclass(frozen=True)
class UpdateLinkPlan:
    url: str

    def as_dict(self):
        return {'url': self.url, 'preference': 'CISDownloadsURL', 'original_verb': 'open',
                'original_show': 1, 'original_launch_result_checked': False,
                'version_comparison_performed': False, 'updates_available': None,
                'browser_opened': False, 'network_accessed': False, 'registry_accessed': False}


def toolkit_download_link(values: Mapping[str, object]) -> UpdateLinkPlan:
    """Plan the original menu handoff within the existing forty-value schema."""
    return UpdateLinkPlan(validate_values(values)['CISDownloadsURL'])


def catalogue_request(installed_version: str) -> bytes:
    """Serialize the original active-node/product-assignment request exactly.

    The explicit bounded string is forwarded unchanged. This is not a SemVer
    parser and does not read this Python package's or the host's installed version.
    """
    _text(installed_version, 'installed_version', 256, empty=False)
    encoded = json.dumps([
        {'nodeStates': ['active'], 'type': 'NodeStateFilter'},
        {'productId': TOOLKIT_PRODUCT_ID, 'version': installed_version,
         'includeParents': False, 'type': 'ProductAssignmentFilter'},
    ], ensure_ascii=False, separators=(',', ':'))
    # Original Newtonsoft default escaping includes these JavaScript line
    # separators even when non-ASCII characters otherwise remain literal.
    for character in ('\u0085', '\u2028', '\u2029'):
        encoded = encoded.replace(character, '\\u' + format(ord(character), '04x'))
    return encoded.encode('utf-8')


@dataclass(frozen=True)
class UpdateFailure:
    stage: str
    type: str
    message: str

    @classmethod
    def from_error(cls, stage, error):
        try:
            message = str(error) or type(error).__name__
        except BaseException:
            message = '<exception message unavailable>'
        message = message.encode('utf-8', 'backslashreplace').decode('utf-8')
        return cls(stage, type(error).__name__, message[:4096])

    def as_dict(self):
        return {'stage': self.stage, 'type': self.type, 'message': self.message}


@dataclass(frozen=True)
class UpdateCleanup:
    resource: str
    succeeded: bool
    error: UpdateFailure | None = None

    def as_dict(self):
        return {'resource': self.resource, 'attempted': True, 'succeeded': self.succeeded,
                'error': self.error.as_dict() if self.error else None}


@dataclass(frozen=True)
class CatalogueHTTPReply:
    status: int | None
    headers: tuple[tuple[str, str], ...]
    body: bytes
    bytes_received: int
    body_complete: bool
    request_attempted: bool
    error: UpdateFailure | None = None
    cleanup: tuple[UpdateCleanup, ...] = ()
    cause: BaseException | None = field(default=None, repr=False, compare=False)

    @property
    def complete(self):
        return self.body_complete and self.error is None and all(item.succeeded for item in self.cleanup)

    def as_dict(self):
        return {'status': self.status, 'headers': [list(pair) for pair in self.headers],
                'body_bytes_retained': len(self.body), 'bytes_received': self.bytes_received,
                'body_sha256': hashlib.sha256(self.body).hexdigest(), 'body_complete': self.body_complete,
                'request_attempted': self.request_attempted, 'complete': self.complete,
                'error': self.error.as_dict() if self.error else None,
                'cleanup': [item.as_dict() for item in self.cleanup], 'end_to_end_deadline_bounded': False}


class CatalogueTransport(Protocol):
    last_reply: CatalogueHTTPReply | None

    def post(self, body: bytes, *, timeout: float, max_response_bytes: int) -> CatalogueHTTPReply: ...


def _validate_reply(reply, maximum):
    if type(reply) is not CatalogueHTTPReply:
        raise TypeError('Transport must return CatalogueHTTPReply')
    if type(reply.body) is not bytes or len(reply.body) > maximum:
        raise ValueError('Transport returned an invalid or oversized body')
    _integer(reply.bytes_received, 'bytes_received', len(reply.body), 2**63 - 1)
    if type(reply.body_complete) is not bool or type(reply.request_attempted) is not bool:
        raise ValueError('Transport completion and attempt flags must be booleans')
    if reply.status is not None: _integer(reply.status, 'HTTP status', 100, 599)
    if reply.body_complete and (not reply.request_attempted or reply.status is None or reply.bytes_received != len(reply.body)):
        raise ValueError('Transport complete-body evidence is inconsistent')
    if type(reply.headers) is not tuple or len(reply.headers) > 100:
        raise ValueError('Transport headers must be a bounded tuple')
    for pair in reply.headers:
        if type(pair) is not tuple or len(pair) != 2: raise ValueError('Invalid transport header')
        _text(pair[0], 'header name', 65536); _text(pair[1], 'header value', 65536)
    if type(reply.cleanup) is not tuple or len(reply.cleanup) > 2:
        raise ValueError('Transport cleanup must be a bounded tuple')
    for cleanup in reply.cleanup:
        if type(cleanup) is not UpdateCleanup or type(cleanup.succeeded) is not bool:
            raise ValueError('Invalid transport cleanup evidence')
        if cleanup.resource not in ('connection', 'response'): raise ValueError('Unknown cleanup resource')
        if cleanup.succeeded != (cleanup.error is None): raise ValueError('Inconsistent cleanup outcome')
    for error in (reply.error, *(cleanup.error for cleanup in reply.cleanup)):
        if error is not None:
            if type(error) is not UpdateFailure: raise ValueError('Invalid transport error evidence')
            _text(error.stage, 'error stage', 256); _text(error.type, 'error type', 256)
            # An OS error's rendered message is evidence, not a native string or URL.
            if type(error.message) is not str or len(error.message) > 4096:
                raise ValueError('Invalid transport error message')
    if reply.cause is not None and not isinstance(reply.cause, BaseException):
        raise ValueError('Invalid transport cause')
    return reply


class HTTPSCatalogueTransport:
    """One verified-TLS POST to the fixed endpoint per call, no redirects/retry.

    The timeout applies to blocking socket operations, not a hard total duration;
    DNS, TLS setup and cleanup retain their platform limitations. A custom context
    may select trusted CAs but must require certificates and hostname checking.
    Environment proxy settings are not used. Every acquired response/connection
    receives one explicit close attempt; interruption identity is preserved.
    """
    def __init__(self, *, context: ssl.SSLContext | None = None):
        if context is not None and (not isinstance(context, ssl.SSLContext) or
                                   context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname):
            raise ValueError('TLS context must require certificate and hostname verification')
        self._context = context
        self.last_reply = None

    def post(self, body: bytes, *, timeout: float, max_response_bytes: int) -> CatalogueHTTPReply:
        self.last_reply = None
        _timeout(timeout); _integer(max_response_bytes, 'max_response_bytes', 1, 16 * 1024 * 1024)
        if type(body) is not bytes or len(body) > 4096:
            raise ValueError('request body must be at most 4096 bytes')
        connection = response = None
        status = None; headers = (); retained = bytearray(); received = 0
        complete = attempted = False; failure = cause = interruption = None; cleanup = []
        stage = 'tls_setup'
        try:
            context = self._context or ssl.create_default_context()
            if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
                raise ValueError('TLS context no longer requires certificate and hostname verification')
            connection = http.client.HTTPSConnection(CATALOGUE_HOST, 443, timeout=timeout, context=context)
            stage = 'request'; attempted = True
            connection.request('POST', CATALOGUE_PATH, body=body, headers={
                'Accept': 'application/json', 'Content-Type': 'application/json; charset=utf-8'})
            stage = 'response_headers'; response = connection.getresponse()
            status = response.status
            headers = tuple(response.getheaders())
            lengths = [value for key, value in headers if key.lower() == 'content-length']
            encodings = [value for key, value in headers if key.lower() == 'content-encoding']
            transfers = [value for key, value in headers if key.lower() == 'transfer-encoding']
            if len(lengths) > 1 or (lengths and transfers):
                raise ValueError('Ambiguous HTTP response framing')
            if encodings and (len(encodings) != 1 or encodings[0].lower().strip() != 'identity'):
                raise ValueError('Encoded HTTP response is outside the bounded catalogue scope')
            if transfers and (len(transfers) != 1 or transfers[0].lower().strip() != 'chunked'):
                raise ValueError('Unsupported HTTP transfer encoding')
            declared = None
            if lengths:
                if not lengths[0].isascii() or not lengths[0].isdigit():
                    raise ValueError('Invalid HTTP Content-Length')
                declared = int(lengths[0])
                if declared > max_response_bytes:
                    raise ValueError('HTTP response exceeds max_response_bytes')
            stage = 'response_body'
            while True:
                try:
                    chunk = response.read(min(65536, max_response_bytes - len(retained) + 1))
                except http.client.IncompleteRead as error:
                    received += len(error.partial)
                    retained.extend(error.partial[:max_response_bytes - len(retained)])
                    raise
                if type(chunk) is not bytes:
                    raise TypeError('HTTP response reader did not return bytes')
                received += len(chunk)
                retained.extend(chunk[:max_response_bytes - len(retained)])
                if received > max_response_bytes:
                    raise ValueError('HTTP response exceeds max_response_bytes')
                if not chunk:
                    if declared is not None and received != declared:
                        raise ValueError('HTTP body is shorter than Content-Length')
                    complete = True
                    break
        except BaseException as error:
            cause = error; failure = UpdateFailure.from_error(stage, error)
            if not isinstance(error, Exception): interruption = error
        finally:
            for name, resource in (('response', response), ('connection', connection)):
                if resource is None: continue
                try:
                    resource.close()
                    cleanup.append(UpdateCleanup(name, True))
                except BaseException as error:
                    detail = UpdateFailure.from_error(name + '_close', error)
                    cleanup.append(UpdateCleanup(name, False, detail))
                    if failure is None: failure, cause = detail, error
                    # A later cleanup interruption must not replace an already
                    # recorded operational failure; it remains separate evidence.
                    if not isinstance(error, Exception) and interruption is None and cause is error:
                        interruption = error
            self.last_reply = CatalogueHTTPReply(status, headers, bytes(retained), received,
                complete, attempted, failure, tuple(cleanup), cause)
        if interruption is not None:
            raise interruption
        return self.last_reply


def _object(value, name):
    if type(value) is not dict:
        raise ValueError(name + ' must be a JSON object')
    return value


def _localized(value, name):
    value = _object(value, name)
    if len(value) > 128: raise ValueError(name + ' has too many locales')
    return tuple((_text(key, name + ' locale', 128, empty=False), _text(text, name, 16384))
                 for key, text in value.items())


@dataclass(frozen=True)
class CatalogueFile:
    id: str
    name: str
    size: int
    url: str
    architecture: str | None

    def as_dict(self):
        return {'id': self.id, 'name': self.name, 'size': self.size, 'url': self.url,
                'architecture': self.architecture, 'downloaded': False}


@dataclass(frozen=True)
class CatalogueCandidate:
    node_id: str
    name: str
    display_names: tuple[tuple[str, str], ...]
    additional_info_urls: tuple[tuple[str, str], ...]
    files: tuple[CatalogueFile, ...]
    signature_present: bool

    def as_dict(self):
        return {'node_id': self.node_id, 'name': self.name, 'display_names': dict(self.display_names),
                'additional_info_urls': dict(self.additional_info_urls),
                'files': [item.as_dict() for item in self.files], 'metadata_signature_present': self.signature_present,
                'metadata_signature_verified': False, 'applicability_verified': False, 'version': None}


def _candidate(value):
    value = _object(value, 'candidate'); data = _object(value.get('data'), 'candidate.data')
    if data.get('type') != 'PackageData': raise ValueError('Only PackageData candidates are supported')
    node_id = _text(value.get('nodeId'), 'nodeId', 256, empty=False)
    name = _text(value.get('nodeName'), 'nodeName', 4096, empty=False)
    display = _localized(data.get('displayName', {}), 'displayName')
    links = _localized(data.get('additionalInfoUrl', {}), 'additionalInfoUrl')
    files = value.get('files')
    if type(files) is not list or len(files) > 64:
        raise ValueError('candidate.files must be an array of at most 64 entries')
    parsed = []; ids = set()
    for item in files:
        item = _object(item, 'file'); file_id = _text(item.get('id'), 'file.id', 256, empty=False)
        if file_id in ids: raise ValueError('Duplicate file id')
        ids.add(file_id)
        metadata = _object(item.get('metadata', {}), 'file.metadata')
        architecture = metadata.get('architecture')
        if architecture is not None: _text(architecture, 'file architecture', 256)
        parsed.append(CatalogueFile(file_id, _text(item.get('name'), 'file.name', 4096, empty=False),
            _integer(item.get('size'), 'file.size', 0, 2**63 - 1),
            _text(item.get('url'), 'file.url', 16384, empty=False), architecture))
    signatures = _object(value.get('signatures', {}), 'signatures')
    if len(signatures) > 16: raise ValueError('Too many metadata signatures')
    for key, signature in signatures.items():
        _text(key, 'signature version', 128, empty=False); _text(signature, 'signature', 32768)
    return CatalogueCandidate(node_id, name, display, links, tuple(parsed), bool(signatures.get('v1')))


def _json(body):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise ValueError('Duplicate JSON key: ' + key[:128])
            value[key] = item
        return value
    def constant(value): raise ValueError('Non-finite JSON number: ' + value)
    def floating(value):
        result = float(value)
        if not math.isfinite(result): raise ValueError('Non-finite JSON number')
        return result
    return json.loads(body.decode('utf-8'), object_pairs_hook=unique, parse_constant=constant, parse_float=floating)


@dataclass(frozen=True)
class CatalogueOutcome:
    installed_version: str
    request_body: bytes
    reply: CatalogueHTTPReply | None
    body_success: bool | None
    body_status: int | None
    body_message: str | None
    candidates: tuple[CatalogueCandidate, ...]
    error: UpdateFailure | None
    cause: BaseException | None = field(default=None, repr=False, compare=False)

    @property
    def complete(self):
        return self.error is None and self.reply is not None and self.reply.complete

    def as_dict(self):
        return {'scope': 'Unverified server-assigned catalogue candidates', 'complete': self.complete,
                'endpoint': CATALOGUE_URL, 'installed_version': self.installed_version,
                'request_sha256': hashlib.sha256(self.request_body).hexdigest(),
                'http': self.reply.as_dict() if self.reply else None,
                'body_success': self.body_success, 'body_status': self.body_status, 'body_message': self.body_message,
                'candidates': [item.as_dict() for item in self.candidates],
                'error': self.error.as_dict() if self.error else None,
                'metadata_signature_verified': False, 'applicability_verified': False,
                'updates_available': None, 'latest_version': None, 'version_comparison_performed': False,
                'downloaded': False, 'installed': False, 'browser_opened': False, 'registry_accessed': False}


class ToolkitUpdateCatalogue:
    def __init__(self, transport: CatalogueTransport, *, max_response_bytes=2097152, max_packages=256):
        _integer(max_response_bytes, 'max_response_bytes', 1, 16 * 1024 * 1024)
        _integer(max_packages, 'max_packages', 1, 4096)
        self.transport = transport; self.max_response_bytes = max_response_bytes; self.max_packages = max_packages
        self.last_outcome = None

    def query(self, installed_version: str, *, timeout=15) -> CatalogueOutcome:
        self.last_outcome = None
        request = catalogue_request(installed_version); timeout = _timeout(timeout)
        reply = None; success = status = message = None; candidates = (); failure = cause = None
        stage = 'transport'; previous = None; post_entered = False
        try:
            previous = getattr(self.transport, 'last_reply', None)
            post_entered = True
            received = self.transport.post(request, timeout=timeout, max_response_bytes=self.max_response_bytes)
            reply = _validate_reply(received, self.max_response_bytes)
            if not reply.complete:
                failure = reply.error or UpdateFailure('transport', 'IncompleteReply', 'HTTP exchange was incomplete')
                cause = reply.cause
            else:
                stage = 'http_status'
                if type(reply.status) is not int or reply.status != 200:
                    raise ValueError('Catalogue requires HTTP status 200')
                stage = 'json'; document = _object(_json(reply.body), 'response')
                stage = 'body_status'
                success = document.get('success'); status = document.get('statusCode'); message = document.get('message')
                if type(success) is not bool: raise ValueError('response.success must be a boolean')
                _integer(status, 'response.statusCode', 100, 599); _text(message, 'response.message', 4096)
                if not success or status != 200: raise ValueError('Catalogue body reported failure')
                stage = 'candidates'; values = document.get('data')
                if type(values) is not list or len(values) > self.max_packages:
                    raise ValueError('response.data must be an array within max_packages')
                candidates = tuple(_candidate(value) for value in values)
                if len({item.node_id for item in candidates}) != len(candidates):
                    candidates = (); raise ValueError('Duplicate candidate nodeId')
        except BaseException as error:
            cause = error; failure = UpdateFailure.from_error(stage, error)
            if reply is None and post_entered:
                try: fresh = getattr(self.transport, 'last_reply', None)
                except BaseException: fresh = None
                if fresh is not previous:
                    try: reply = _validate_reply(fresh, self.max_response_bytes)
                    except BaseException: pass
            # Only correctly typed status fields are retained after invalid JSON shapes.
            success = success if type(success) is bool else None
            status = status if type(status) is int and 100 <= status <= 599 else None
            try: message = _text(message, 'response.message', 4096) if message is not None else None
            except BaseException: message = None
            self.last_outcome = CatalogueOutcome(installed_version, request, reply, success, status, message,
                candidates, failure, cause)
            if not isinstance(error, Exception):
                try: error.toolkit_update_evidence = self.last_outcome.as_dict()
                except BaseException: pass
                raise
        self.last_outcome = CatalogueOutcome(installed_version, request, reply, success, status, message,
            candidates, failure, cause)
        return self.last_outcome
