"""Offline, bounded SESU metadata diagnostics using an explicitly untrusted key.

No network, registry, clock, certificate-store, trust or applicability operations.
The supported canonical domain deliberately excludes unproved Newtonsoft/culture
coercions. Cryptographic validity for a supplied key is not publisher trust.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import math
import re
import uuid

PROFILE = 'sesu-3.0.7-captured-package-v1'
MAX_NODE_BYTES = 2 * 1024 * 1024
MAX_CERTIFICATE_BYTES = 65536
MAX_TOKEN_CHARACTERS = 256000
TICKS_PER_SECOND = 10000000
EPOCH_TICKS = 621355968000000000
MAX_TICKS = 3155378975999999999
CLOCK_SKEW_SECONDS = 300
STAGES = ('canonicalization', 'jwt_parsing', 'certificate_identity',
          'jwt_cryptographic_signature', 'jwt_lifetime', 'payload_digest_claim')
_INSTANT = re.compile(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,7}))?Z\Z', re.ASCII)
_DATE_TEXT = re.compile(r'(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|/Date\()')
_GUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
_THUMBPRINT = re.compile(r'[0-9A-F]{40}\Z')


class _Domain(ValueError):
    pass


class _UnsupportedKey(ValueError):
    pass


def _error(error):
    try:
        text = str(error)
    except BaseException:
        text = '<exception message unavailable>'
    return {'type': type(error).__name__, 'message': text.encode('utf-8', 'backslashreplace').decode()[:4096]}


def _bytes(value, name, limit):
    if type(value) is not bytes or not 0 < len(value) <= limit:
        raise ValueError(name + ' must be nonempty bytes within its size limit')


def _json(raw, *, limit=MAX_NODE_BYTES, depth_limit=32):
    _bytes(raw, 'JSON input', limit)
    text = raw.decode('utf-8')
    depth = tokens = 0
    quoted = escaped = False
    # Bound nesting and punctuation before the JSON decoder allocates its tree.
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            tokens += 1
            if depth > depth_limit:
                raise ValueError('JSON nesting exceeds supported bound')
        elif char in ']}':
            depth -= 1
        elif char in ',:':
            tokens += 1
        if tokens > 32768:
            raise ValueError('JSON structure exceeds supported bound')

    def integer(value):
        if len(value.lstrip('-')) > 19:
            raise ValueError('JSON integer exceeds the bounded decimal digit count')
        return int(value)

    def floating(value):
        if len(value) > 128:
            raise ValueError('JSON number exceeds supported text bound')
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Non-finite JSON numbers are unsupported')
        return result

    def constant(value):
        raise ValueError('Non-finite JSON numbers are unsupported')

    def unique(pairs):
        if len(pairs) > 1024:
            raise ValueError('JSON object exceeds supported member count')
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError('Duplicate JSON key')
            result[name] = value
        return result

    value = json.loads(text, parse_int=integer, parse_float=floating,
                       parse_constant=constant, object_pairs_hook=unique)
    pending = [value]
    count = 0
    while pending:
        item = pending.pop()
        count += 1
        if count > 32768:
            raise ValueError('JSON value count exceeds supported bound')
        if type(item) is str:
            if len(item) > 262144 or any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                raise ValueError('JSON string exceeds its bound or contains an unpaired surrogate')
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return value


def _encode(value, *, sorted_keys=False):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'),
                      sort_keys=sorted_keys, allow_nan=False)
    for char in ('\u0085', '\u2028', '\u2029'):
        text = text.replace(char, '\\u' + format(ord(char), '04x'))
    return text.encode('utf-8')


def validate_node_id(node_id):
    if type(node_id) is not str or not 0 < len(node_id) <= 256 or any(0xD800 <= ord(c) <= 0xDFFF for c in node_id):
        raise ValueError('node_id must be bounded Unicode text')


def select_node(raw_response: bytes, *, node_id: str) -> bytes:
    """Return normalized JSON for one unique node, not an original byte slice."""
    validate_node_id(node_id)
    response = _json(raw_response)
    if type(response) is not dict or type(response.get('data')) is not list or len(response['data']) > 256:
        raise ValueError('Expected a bounded raw catalogue data array')
    if any(type(node) is not dict for node in response['data']):
        raise ValueError('Catalogue data must contain node objects')
    found = [node for node in response['data'] if node.get('nodeId') == node_id]
    if len(found) != 1:
        raise ValueError('Expected exactly one node with the selected node_id')
    return _encode(found[0])


def _instant(value):
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError('Evaluation time must be an explicitly UTC-aware datetime')
        text = (f'{value.year:04}-{value.month:02}-{value.day:02}T{value.hour:02}:{value.minute:02}:{value.second:02}'
                + ('.' + f'{value.microsecond:06}'.rstrip('0') if value.microsecond else '') + 'Z')
    elif type(value) is str and len(value) <= 28:
        text = value
    else:
        raise ValueError('Time must be explicit UTC text with at most seven fractional digits, or a UTC datetime')
    match = _INSTANT.fullmatch(text)
    if not match:
        raise ValueError('Time must use YYYY-MM-DDTHH:MM:SS[.fffffff]Z')
    year, month, day, hour, minute, second = map(int, match.groups()[:6])
    fraction = (match[7] or '').ljust(7, '0')
    instant = datetime(year, month, day, hour, minute, second)
    ticks = ((instant.toordinal() - 1) * 86400 + hour * 3600 + minute * 60 + second) * TICKS_PER_SECOND + int(fraction or '0')
    suffix = fraction.rstrip('0')
    return ticks, f'{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}' + ('.' + suffix if suffix else '') + 'Z'


def validate_context(at_utc, *, culture='invariant', timezone='UTC'):
    if type(culture) is not str or culture != 'invariant' or type(timezone) is not str or timezone != 'UTC':
        raise ValueError('The supported canonical context is culture=invariant and timezone=UTC')
    return _instant(at_utc)


def _object(value, name, allowed):
    if type(value) is not dict or set(value) - set(allowed):
        raise _Domain(name + ' has an unsupported object shape or unknown field')
    return value


def _text(value, name, *, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not str or len(value) > 16384:
        raise _Domain(name + ' must be bounded text')
    if _DATE_TEXT.match(value):
        raise _Domain(name + ' is date-like text with unproved local-time reparsing semantics')
    return value


def _integer(value, name, bits=32):
    if type(value) is not int or not -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
        raise _Domain(name + ' must be a signed Int' + str(bits) + ' value without coercion')
    return value


def _texts(value, name, allowed):
    obj = _object(value, name, allowed)
    return {key: _text(text, name + '.' + key) for key, text in obj.items()}


def _date(value, name):
    try:
        if type(value) is not str:
            raise ValueError('Typed date must be a string')
        return _instant(value)
    except ValueError as error:
        raise _Domain(name + ' must be a valid UTC date with at most seven fractional digits') from error


def _data(value):
    if value is None:
        return None
    obj = _object(value, 'data', ('type', 'additionalInfoUrl', 'installationInstruction', 'severity',
        'visibilityInPercent', 'startDate', 'expireDate', 'clientConditionData', 'forcedUpdate',
        'automaticUpdate', 'displayName', 'description'))
    if obj.get('type') != 'PackageData':
        raise _Domain('Only the PackageData model is supported')
    result = {'type': 'PackageData'}
    if 'severity' in obj:
        if obj['severity'] not in ('normal', 'critical'):
            raise _Domain('Only exact normal/critical severity names are supported')
        if obj['severity'] == 'critical':
            result['severity'] = 'critical'
    for key in ('forcedUpdate', 'automaticUpdate'):
        item = obj.get(key, False)
        if type(item) is not bool:
            raise _Domain(key + ' must be boolean')
        result[key] = item
    for key in ('additionalInfoUrl', 'installationInstruction', 'displayName', 'description'):
        if obj.get(key) is not None:
            result[key] = _texts(obj[key], 'data.' + key, ('default', 'en'))
    if 'visibilityInPercent' in obj:
        number = _integer(obj['visibilityInPercent'], 'visibilityInPercent')
        if number:
            result['visibilityInPercent'] = number
    for key in ('startDate', 'expireDate'):
        if key in obj:
            ticks, text = _date(obj[key], key)
            if ticks:
                result[key] = text
    if obj.get('clientConditionData') is not None:
        condition = _object(obj['clientConditionData'], 'clientConditionData', ('conditions', 'expression'))
        result['clientConditionData'] = {}
        if condition.get('conditions') is not None:
            if type(condition['conditions']) is not dict or condition['conditions']:
                raise _Domain('Only empty conditions are in the supported canonical model domain')
            result['clientConditionData']['conditions'] = {}
        if condition.get('expression') is not None:
            result['clientConditionData']['expression'] = _text(condition['expression'], 'condition.expression')
    return result


def _header(value):
    if value is None:
        return None
    header = _object(value, 'header', ('revision', 'versionHistory'))
    revision = header.get('revision')
    if revision is None:
        return {'revision': None}
    obj = _object(revision, 'revision', ('revisionId', 'changeId', 'timestamp', 'state', 'author'))
    if not {'revisionId', 'changeId', 'timestamp', 'state'} <= set(obj):
        raise _Domain('Non-null revision requires its four original fields')
    if type(obj['revisionId']) is not str or not _GUID.fullmatch(obj['revisionId']):
        raise _Domain('revisionId requires a dashed Guid')
    if obj['state'] != 'active':
        raise _Domain('Only the captured active revision state is supported')
    return {'revision': {'revisionId': str(uuid.UUID(obj['revisionId'])),
        'changeId': _integer(obj['changeId'], 'changeId', 64),
        'timestamp': _date(obj['timestamp'], 'revision.timestamp')[1], 'state': 'active'}}


def _assignments(value):
    if value is None:
        return None
    if type(value) is not list or len(value) > 256:
        raise _Domain('assignedTo must be a bounded array or null')
    result, seen = [], set()
    for item in value:
        if item is None:
            normalized = None
        else:
            obj = _object(item, 'assignment', ('type', 'target'))
            if obj.get('type') not in ('product', 'parent'):
                raise _Domain('Unsupported assignment model type')
            target = _object(obj.get('target'), 'assignment.target', ('type', 'collection', 'nodeId'))
            if target.get('type') not in ('node', 'collection') or target.get('collection') not in ('ProductVersionData', 'PackageData'):
                raise _Domain('Unsupported assignment target model')
            if (obj['type'], target['type'], target['collection']) not in (
                    ('product', 'node', 'ProductVersionData'), ('parent', 'collection', 'PackageData')):
                raise _Domain('Assignment type/target combination is outside the captured model shapes')
            normalized_target = {'type': target['type'], 'collection': target['collection']}
            if target['type'] == 'node':
                normalized_target['nodeId'] = _text(target.get('nodeId'), 'target.nodeId')
            elif 'nodeId' in target:
                raise _Domain('Collection reference cannot have a nodeId in this profile')
            normalized = {'type': obj['type'], 'target': normalized_target}
        fingerprint = _encode(normalized, sorted_keys=True)
        if fingerprint in seen:
            raise _Domain('Duplicate assignment HashSet normalization is outside this profile')
        seen.add(fingerprint)
        result.append(normalized)
    return result


def _files(value):
    if value is None:
        return None
    if type(value) is not list or len(value) > 64:
        raise _Domain('files must be a bounded array or null')
    result = []
    for item in value:
        if item is None:
            result.append(None)
            continue
        obj = _object(item, 'file', ('id', 'name', 'size', 'url', 'security', 'metadata'))
        if obj.get('url') is not None and type(obj['url']) is not str:
            raise _Domain('Excluded file.url must still have its original string model shape')
        file = {'id': _text(obj.get('id'), 'file.id'), 'name': _text(obj.get('name'), 'file.name'),
                'size': _integer(obj.get('size'), 'file.size'), 'security': None}
        if obj.get('security') is not None:
            file['security'] = _texts(obj['security'], 'file.security', ('sha1',))
        if obj.get('metadata') is not None:
            file['metadata'] = _texts(obj['metadata'], 'file.metadata', ('architecture', 'mediatype'))
        result.append(file)
    return result


def _canonical(node):
    obj = _object(node, 'node', ('urls', 'header', 'data', 'nodeId', 'nodeName', 'assignedTo', 'files', 'signatures'))
    if obj.get('urls') is not None:
        if type(obj['urls']) is not dict or len(obj['urls']) > 64:
            raise _Domain('Excluded urls must still have their original dictionary model shape')
        for value in obj['urls'].values():
            row = _object(value, 'urls entry', ('url',))
            if row.get('url') is not None and type(row['url']) is not str:
                raise _Domain('Excluded URL must be a string or null')
    if obj.get('signatures') is not None:
        if type(obj['signatures']) is not dict or len(obj['signatures']) > 16 or any(type(v) is not str and v is not None for v in obj['signatures'].values()):
            raise _Domain('Excluded signatures must have their original string dictionary model shape')
    result = {'nodeId': _text(obj.get('nodeId'), 'nodeId'), 'nodeName': _text(obj.get('nodeName'), 'nodeName', nullable=True),
              'header': _header(obj.get('header')), 'data': _data(obj.get('data')),
              'assignedTo': _assignments(obj.get('assignedTo', [])), 'files': _files(obj.get('files', []))}
    # Only the explicit fixed field/key sets above reach this ordering. Their
    # ordinal and original invariant-culture order are proved by the fixtures.
    return _encode(result, sorted_keys=True)


def _base64url(text):
    if type(text) is not str or not text or len(text) > MAX_TOKEN_CHARACTERS or not re.fullmatch(r'[A-Za-z0-9_-]+', text, re.ASCII):
        raise _Domain('JWT components require bounded unpadded base64url')
    try:
        result = base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_', validate=True)
    except ValueError as error:
        raise _Domain('Invalid JWT base64url') from error
    if base64.urlsafe_b64encode(result).rstrip(b'=').decode() != text:
        raise _Domain('Noncanonical JWT base64url is outside this profile')
    return result


def _token(node, *, policy='v1'):
    if type(policy) is not str or policy not in ('v1', 'rv1'):
        raise ValueError('Unsupported internal JWT policy')
    signatures = node.get('signatures')
    if type(signatures) is not dict or type(signatures.get(policy)) is not str or not signatures[policy]:
        raise _Domain('A nonempty signatures.' + policy + ' compact JWT is required')
    text = signatures[policy]
    if len(text) > MAX_TOKEN_CHARACTERS or text.count('.') != 2:
        raise _Domain('JWT size or compact component count is outside this profile')
    header_part, payload_part, signature_part = text.split('.')
    header = _json(_base64url(header_part), limit=MAX_TOKEN_CHARACTERS, depth_limit=16)
    payload = _json(_base64url(payload_part), limit=MAX_TOKEN_CHARACTERS, depth_limit=16)
    header = _object(header, 'JWT header', ('alg', 'kid', 'typ', 'x5t', 'pol', 'crit'))
    payload = _object(payload, 'JWT claims', ('nbf', 'exp', 'iat', 'payload_sha256', 'iss', 'aud'))
    if type(header.get('alg')) is not str or len(header['alg']) > 64:
        raise _Domain('JWT alg must be a bounded string')
    if header.get('typ') != 'JWT' or header.get('pol') != policy or header.get('crit') != ['pol']:
        raise _Domain('JWT type, policy and critical headers are outside the known ' + policy + ' shape')
    if type(header.get('x5t')) is not str or not _THUMBPRINT.fullmatch(header['x5t']):
        raise _Domain('JWT x5t must use the original uppercase hexadecimal thumbprint shape')
    if 'kid' in header and (type(header['kid']) is not str or len(header['kid']) > 256):
        raise _Domain('JWT kid must be bounded text')
    for key in ('nbf', 'exp', 'iat'):
        if key in payload:
            _integer(payload[key], 'JWT ' + key, 64)
    for key in ('iss', 'aud'):
        if key in payload and (type(payload[key]) is not str or len(payload[key]) > 4096):
            raise _Domain('Optional unvalidated issuer/audience must be bounded strings')
    if 'payload_sha256' in payload and (type(payload['payload_sha256']) is not str or len(payload['payload_sha256']) > 128):
        raise _Domain('JWT payload_sha256 must be a single bounded string')
    signature = _base64url(signature_part) if signature_part else b''
    return header, payload, (header_part + '.' + payload_part).encode('ascii'), signature


def _load_certificate(raw):
    # Lazy optional dependency; no subject/issuer string rendering or trust store.
    from cryptography import x509
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives.asymmetric import rsa
    try:
        certificate = x509.load_der_x509_certificate(raw)
        key = certificate.public_key()
    except UnsupportedAlgorithm as error:
        raise _UnsupportedKey('Supplied certificate uses an unsupported public-key algorithm') from error
    return key, isinstance(key, rsa.RSAPublicKey)


def _verify_signature(key, signature, signing_input):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        return False


def _epoch(seconds):
    return min(MAX_TICKS, EPOCH_TICKS + max(seconds, 0) * TICKS_PER_SECOND)


@dataclass(frozen=True)
class MetadataStageReport:
    _document: str = field(repr=False)
    cause: BaseException | None = field(default=None, repr=False, compare=False)

    def as_dict(self):
        return json.loads(self._document)

    @property
    def all_supported_stages_passed(self):
        return all(row['status'] == 'passed' for row in self.as_dict()['stages'])


class ToolkitUpdateMetadataStages:
    def __init__(self):
        self.last_report = None

    def evaluate(self, raw_node_json: bytes, *, certificate_der: bytes, at_utc,
                 culture='invariant', timezone='UTC') -> MetadataStageReport:
        self.last_report = None
        ticks, time_text = validate_context(at_utc, culture=culture, timezone=timezone)
        _bytes(certificate_der, 'certificate_der', MAX_CERTIFICATE_BYTES)
        node = _json(raw_node_json)
        if type(node) is not dict:
            raise ValueError('Metadata input must be a complete node JSON object')
        document = {'scope': 'Independent offline stages for an explicitly untrusted supplied certificate',
            'profile': PROFILE, 'input_node_sha256': hashlib.sha256(raw_node_json).hexdigest(),
            'certificate_der_sha256': hashlib.sha256(certificate_der).hexdigest(),
            'certificate_thumbprint_sha1': hashlib.sha1(certificate_der).hexdigest().upper(),
            'evaluation_time_utc': time_text, 'evaluation_ticks_100ns': ticks,
            'clock_skew_seconds': CLOCK_SKEW_SECONDS, 'culture': culture, 'timezone': timezone,
            'publisher_trust': {'status': 'not_evaluated', 'reason': 'Supplied DER is not a trust anchor'},
            'revocation': {'status': 'not_evaluated', 'reason': 'No signed revocation material was evaluated'},
            'applicability': {'status': 'not_evaluated', 'reason': 'No local machine or rollout conditions were evaluated'},
            'network_accessed': False, 'registry_accessed': False, 'certificate_store_accessed': False,
            'stages': [{'stage': name, 'status': 'not_run'} for name in STAGES]}
        rows = {row['stage']: row for row in document['stages']}
        current = 'canonicalization'
        def record(name, status, **details):
            rows[name].update(status=status, **details)
        def finish(cause=None):
            self.last_report = MetadataStageReport(json.dumps(document, ensure_ascii=True, allow_nan=False), cause)
            return self.last_report
        try:
            canonical = token = key = None
            try:
                canonical = _canonical(node)
                digest = base64.b64encode(hashlib.sha256(canonical).digest()).decode()
                record(current, 'passed', canonical_utf8=canonical.decode(), sha256_base64=digest,
                       sha256_hex=hashlib.sha256(canonical).hexdigest())
            except _Domain as error:
                record(current, 'unsupported', reason=str(error), policy='Explicit finite canonical domain')
            current = 'jwt_parsing'
            try:
                token = _token(node)
                header, payload, signing_input, signature = token
                record(current, 'passed', algorithm=header['alg'], policy=header['pol'], x5t=header['x5t'],
                       kid_used_as_resolver=False, issuer_validated=False, audience_validated=False)
            except ValueError as error:
                record(current, 'unsupported', reason=str(error), policy='Strict bounded JWT domain; broader original forms are excluded')
            current = 'certificate_identity'
            try:
                key, is_rsa = _load_certificate(certificate_der)
                if token is None:
                    record(current, 'not_run', reason='No supported JWT thumbprint to compare')
                else:
                    matches = header['x5t'] == document['certificate_thumbprint_sha1']
                    record(current, 'passed' if matches else 'failed', thumbprint_matches=matches,
                           rsa_public_key=is_rsa, publisher_trust_evaluated=False)
            except ImportError:
                record(current, 'unsupported', reason='Install the existing research extra to provide cryptography')
            except _UnsupportedKey as error:
                record(current, 'unsupported', reason=str(error), error=_error(error.__cause__ or error))
            except (ValueError, TypeError) as error:
                record(current, 'failed', reason='Supplied DER could not be read', error=_error(error))
            current = 'jwt_cryptographic_signature'
            signature_valid = None
            if token is None or key is None:
                record(current, 'not_run', reason='Supported JWT and readable supplied key are required')
            elif header['alg'] != 'RS256' or not is_rsa or not 2048 <= key.key_size <= 8192:
                record(current, 'unsupported', reason='Only RS256 with a supplied RSA key of2048..8192bits is supported')
            else:
                signature_valid = _verify_signature(key, signature, signing_input)
                record(current, 'passed' if signature_valid else 'failed', signature_valid_for_supplied_key=signature_valid,
                       publisher_trust_evaluated=False, certificate_chain_checked=False)
            current = 'jwt_lifetime'
            qualifiers = {'claims_signature_valid_for_supplied_key': signature_valid, 'publisher_trust_evaluated': False}
            if token is None:
                record(current, 'not_run', reason='JWT claim domain is unsupported', **qualifiers)
            else:
                expires = _epoch(payload['exp']) if 'exp' in payload else None
                begins = _epoch(payload['nbf']) if 'nbf' in payload else None
                failure = ('missing_expiration' if expires is None else
                    'not_before_after_expiration' if begins is not None and begins > expires else
                    'not_yet_valid' if begins is not None and begins > min(MAX_TICKS, ticks + CLOCK_SKEW_SECONDS * TICKS_PER_SECOND) else
                    'expired' if expires < max(0, ticks - CLOCK_SKEW_SECONDS * TICKS_PER_SECOND) else None)
                record(current, 'failed' if failure else 'passed', reason=failure,
                       not_before_ticks_100ns=begins, expiration_ticks_100ns=expires, issued_at_is_lifetime_gate=False, **qualifiers)
            current = 'payload_digest_claim'
            if token is None or canonical is None:
                record(current, 'not_run', reason='Supported JWT and canonical payload are required', **qualifiers)
            else:
                matches = payload.get('payload_sha256') == digest
                record(current, 'passed' if matches else 'failed', digest_claim_matches=matches,
                       reason=None if matches else 'Missing or different payload_sha256 claim', **qualifiers)
            return finish()
        except BaseException as error:
            try:
                record(current, 'not_run', reason='Stage interrupted or raised an operational exception', error=_error(error))
                document['interrupted'] = isinstance(error, (KeyboardInterrupt, SystemExit))
                report = finish(error)
            except BaseException:
                # Only fixed/validated identifiers enter this emergency JSON.
                # Avoid calling the failed serializer, exception renderer or any
                # external adapter again while preserving the original object.
                emergency = ('{"scope":"Partial offline metadata-stage evidence",'
                    '"evidence_serialization_failed":true,"original_error_retained":true,'
                    '"publisher_trust_evaluated":false,"stages":[{"stage":"' + current + '","status":"not_run"}],'
                    '"input_node_sha256":"' + document['input_node_sha256'] + '",'
                    '"certificate_der_sha256":"' + document['certificate_der_sha256'] + '"}')
                report = self.last_report = MetadataStageReport(emergency, error)
            try:
                error.toolkit_update_metadata_evidence = report.as_dict()
            except BaseException:
                pass
            raise
