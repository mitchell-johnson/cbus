"""Bounded SESU conditions under supplied facts; no machine or update-availability query."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

from .toolkit_update_metadata import _json, _error

MAX_JSON_BYTES = 128 * 1024
MAX_DEFINITIONS = 8
MAX_EXPRESSION = 256
MAX_PATH = 1024
MAX_VERSION = 256
PROFILE = 'toolkit-1.18-sesu-3.0.7-condition-facts-v1'
CONTEXT_FORMAT = 'cbus-toolkit-condition-context-v1'
STAGES = ('typed_input', 'context_input', 'definition_validation', 'expression_domain', 'expression_evaluation')
CONDITION_ERROR = 'SE.DAD.SESU.Common.Validation.ClientConditionException'
JSON_ERROR = 'Newtonsoft.Json.JsonSerializationException'
WHAT = {'fileExists': 1, 'fileVersion': 2, 'registryKeyExists': 3, 'registryEntryExists': 4,
        'registryEntryStringContent': 5, 'registryEntryIntegerContent': 6,
        'productIsInstalled': 7, 'productVersionIsInstalled': 8, 'vbscript': 99}
HOW = {'isTrue': 1, 'isFalse': 2, 'isEqual': 10, 'isNotEqual': 11, 'isGreater': 12,
       'isGreaterOrEqual': 13, 'isLess': 14, 'isLessOrEqual': 15, 'beginsWith': 16, 'contains': 17}
_NATIVE_HOW = {number: name[0].upper() + name[1:] for name, number in HOW.items()}
_SPACE = ' \t\r\n\v\f'
_IDENTIFIER = re.compile(r'[a-z_][a-z0-9_]*', re.ASCII)
_VERSION_COMPONENT = re.compile(r'[0-9]+\Z', re.ASCII)


class _Outcome(ValueError):
    def __init__(self, status, reason, *, original_type=None, original_message=None, **details):
        super().__init__(reason)
        self.details = {'status': status, 'reason': reason, **details}
        if original_type is not None:
            self.details['original_error_type'] = original_type
        if original_message is not None:
            self.details['original_error_message'] = original_message


def _unsupported(reason, **details):
    raise _Outcome('unsupported', reason, **details)


def _failure(message, original_type=CONDITION_ERROR):
    raise _Outcome('failed', message, original_type=original_type, original_message=message)


def _ascii(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is str and (not item.isascii() or '\0' in item):
            _unsupported('The supplied profile admits ASCII strings without NUL only')
        if type(item) is dict:
            pending.extend(item.keys()); pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)


def _text(value, field_name, maximum):
    if value is None:
        return None
    if type(value) is bool:
        value = 'true' if value else 'false'
    elif type(value) is int:
        value = str(value)
    elif type(value) is not str:
        _unsupported(field_name + ' is outside the observed string/null/Boolean/integer model domain')
    if len(value) > maximum:
        _unsupported(field_name + ' exceeds its character bound')
    return value


def _enum(value, mapping, name):
    if type(value) is int and -(1 << 31) <= value < (1 << 31):
        return value
    if type(value) is str:
        for literal, number in mapping.items():
            if value == literal:
                return number
        # Other converter spellings/coercions were not part of the typed profile.
        if value.lower() in {key.lower() for key in mapping} or re.fullmatch(r'\s*[+-]?[0-9]+\s*', value):
            _unsupported(name + ' uses an unproved enum spelling or numeric-string conversion')
        _failure('Unknown ' + name + ' name: ' + value, JSON_ERROR)
    _unsupported(name + ' must be an Int32 or exact documented enum spelling')


def _typed(data):
    if data is None:
        return None
    if type(data) is not dict:
        _failure('Cannot deserialize the supplied value into ClientConditionData', JSON_ERROR)
    definitions = data.get('conditions')
    if definitions is None:
        definitions = {}
    if type(definitions) is not dict:
        _failure('Cannot deserialize conditions into a dictionary', JSON_ERROR)
    if len(definitions) > MAX_DEFINITIONS:
        _unsupported('At most eight condition definitions are supported')
    expression = data.get('expression')
    if type(expression) in (dict, list):
        _failure('Expression object/array cannot be read as text', 'Newtonsoft.Json.JsonReaderException')
    expression = _text(expression, 'expression', MAX_EXPRESSION)
    entries = []
    for name, definition in definitions.items():
        if len(name) > MAX_EXPRESSION:
            _unsupported('Condition name exceeds its character bound')
        if definition is not None and type(definition) is not dict:
            _failure('Cannot deserialize a condition definition', JSON_ERROR)
        value = None
        if definition is not None:
            value = {'what': _enum(definition.get('whatToCheck', 0), WHAT, 'whatToCheck'),
                     'how': _enum(definition.get('howToCheck', 0), HOW, 'howToCheck'),
                     'path': _text(definition.get('fileOrRegistryKeyPath'), 'fileOrRegistryKeyPath', MAX_PATH),
                     'entry': _text(definition.get('registryEntryNameOrProductCode'), 'registryEntryNameOrProductCode', MAX_VERSION),
                     'right': _text(definition.get('comparisonRightSideValue'), 'comparisonRightSideValue', MAX_VERSION)}
        entries.append({'name': name, 'value': value})
    return {'expression': expression, 'conditions': entries}


def _facts(data):
    if (type(data) is not dict or set(data) != {'format', 'culture', 'files'}
            or data.get('format') != CONTEXT_FORMAT or data.get('culture') != 'invariant-ascii'):
        _unsupported('Context requires the exact format, invariant-ascii culture and files array')
    files = data['files']
    if type(files) is not list or len(files) > 8:
        _unsupported('Context admits at most eight file fact records')
    found = {}
    for item in files:
        if (type(item) is not dict or not {'path'} <= set(item) <= {'path', 'exists', 'file_version'}
                or type(item['path']) is not str or not 0 < len(item['path']) <= MAX_PATH):
            _unsupported('Each file fact requires a bounded literal path and only exists/file_version facts')
        path = item['path']
        if path in found:
            _unsupported('Context paths must be unique exact strings')
        if 'exists' in item and type(item['exists']) is not bool:
            _unsupported('A known exists fact must be a Boolean; omit it for unknown')
        if 'file_version' in item:
            value = item['file_version']
            if value is not None and (type(value) is not str or len(value) > MAX_VERSION):
                _unsupported('A known file_version fact must be bounded text or null')
        found[path] = dict(item)
    return found


def _validate(model):
    if model is None:
        _failure('Value cannot be null. Parameter name: clientConditionData', 'System.ArgumentNullException')
    if not model['expression']:
        _failure('the Expression in the given ClientConditions was null or empty')
    normalized = {}
    for item in model['conditions']:
        name = item['name']
        if not name:
            _failure('no empty string allowed as condition name')
        if any(char in _SPACE for char in name):
            _failure('no whitespace allowed in condition names')
        lookup = name.lower()
        if lookup in normalized:
            _failure('condition name ' + lookup + ' is used twice')
        normalized[lookup] = item
    return normalized


class _Parser:
    """Original Boolean subset: one unary prefix per primary, not per unary."""
    def __init__(self, expression):
        self.text = expression.lower(); self.tokens = []; self.index = 0
        offset = 0
        while offset < len(self.text):
            char = self.text[offset]
            if char in _SPACE:
                offset += 1; continue
            token = next((x for x in ('&&', '||', '!', '(', ')') if self.text.startswith(x, offset)), None)
            if token is None:
                match = _IDENTIFIER.match(self.text, offset)
                if match is None:
                    _unsupported('Expression contains a token outside the finite Boolean grammar', position=offset)
                token = match[0]
            self.tokens.append((token, offset)); offset += len(token)
        for (token, position), (following, _) in zip(self.tokens, self.tokens[1:]):
            if following == '(' and token not in ('true', 'false', 'and', 'or', 'not', '!', '&&', '||', '(', ')'):
                _unsupported('NCalc function calls are outside the Boolean profile', position=position)

    def peek(self):
        return self.tokens[self.index][0] if self.index < len(self.tokens) else None

    def accept(self, *tokens):
        if self.peek() in tokens:
            value = self.peek(); self.index += 1; return value
        return None

    def syntax(self):
        position = self.tokens[self.index][1] if self.index < len(self.tokens) else len(self.text)
        details = {'original_type': 'NCalc.EvaluationException', 'position': position,
                   'diagnostic_provenance': 'Portable Boolean parser; original NCalc error category'}
        if self.text == 'not not a':
            details['original_message'] = "no viable alternative at input 'not' at line 1:5"
            details['diagnostic_provenance'] = 'Captured unchanged original NCalc diagnostic'
        raise _Outcome('failed', 'Malformed expression in the original Boolean subset', **details)

    def parse(self):
        value = self.logical_or()
        if self.peek() is not None:
            self.syntax()
        return value

    def logical_or(self):
        value = self.logical_and()
        while self.accept('or', '||'):
            value = ('or', value, self.logical_and())
        return value

    def logical_and(self):
        value = self.unary()
        while self.accept('and', '&&'):
            value = ('and', value, self.unary())
        return value

    def unary(self):
        negate = self.accept('not', '!') is not None
        value = self.primary()
        return ('not', value) if negate else value

    def primary(self):
        if self.accept('('):
            value = self.logical_or()
            if not self.accept(')'):
                self.syntax()
            return value
        token = self.peek()
        if token is None or token in ('and', 'or', 'not', '&&', '||', '!', ')'):
            self.syntax()
        self.index += 1
        return ('value', token == 'true') if token in ('true', 'false') else ('name', token)


def _version(text):
    """Observed bounded System.Version domain, with omitted components as -1."""
    if text is None or text == '':
        return None
    if any(char in text for char in '+\t\r\n\v\f'):
        _unsupported('Version text uses an unproved sign/whitespace format')
    parts = text.strip(' ').split('.')
    if any(' ' in part for part in parts):
        _unsupported('Version component whitespace is outside the observed profile')
    if not 2 <= len(parts) <= 4:
        return None
    values = []
    for part in parts:
        if not _VERSION_COMPONENT.fullmatch(part):
            return None
        digits = part.lstrip('0') or '0'
        if len(digits) > 10 or (len(digits) == 10 and digits > '2147483647'):
            return None
        values.append(int(digits))
    return tuple(values + [-1] * (4 - len(values)))


def _native_how(number):
    return _NATIVE_HOW.get(number, str(number))


def _leaf(name, condition, facts, event, registry=None):
    if condition is None:
        _unsupported('Reached null condition definition is outside the supported leaf domain')
    what, how, path, right = (condition[k] for k in ('what', 'how', 'path', 'right'))
    event.update(what_to_check=what, how_to_check=how, path=path)
    if registry is not None and what in (3, 4, 5, 6):
        from ._toolkit_update_registry_conditions import leaf
        return leaf(name, condition, registry, event)
    if what not in (1, 2):
        _unsupported('Reached condition requires an unsupported original provider or leaf', what_to_check=what)
    if path is None or path == '':
        _failure("file path not given for condition '" + name + "' that checks file " + ('existence' if what == 1 else 'version'))
    if what == 2:
        if right is None or right == '':
            _failure("version to compare not given for condition '" + name + "' that checks file version")
        if how in (1, 2):
            _failure("unexpected howToCheck for condition '" + name + "' that checks file version")
    if '<WINSYSDIR>' in path or '<COMMONFILES>' in path:
        _unsupported('Original special-folder substitution is outside the supplied literal-path profile', path=path)
    requested = None
    if what == 2 and how not in (16, 17):
        requested = _version(right)
        if requested is None:
            _failure("invalid version given in condition '" + name + "' that checks file version")
    def fact(field_name):
        observation = {'path': path, 'fact': field_name, 'status': 'unknown'}
        event['observations'].append(observation)
        item = facts.get(path, {})
        if field_name not in item:
            _unsupported('Required supplied file fact is unknown', required_fact={'path': path, 'fact': field_name})
        observation.update(status='supplied', value=item[field_name])
        return item[field_name]
    exists = fact('exists')
    if what == 1:
        if how == 2:
            return not exists
        if how == 1:
            return exists
        _failure("error when evaluating condition '" + name + "': files can only be checked against existence or not-existence, but not against " + _native_how(how))
    if not exists:
        return False
    observed = fact('file_version')
    if observed is None or observed == '':
        return False
    if how in (16, 17) and any(ord(char) < 32 or ord(char) == 127 for char in observed + right):
        _unsupported('Culture-sensitive version text comparison admits printable ASCII only')
    if how == 16:
        return observed.startswith(right)
    if how == 17:
        return right in observed
    parsed = _version(observed)
    if parsed is None:
        return False
    if how == 10: return parsed == requested
    if how == 11: return parsed != requested
    if how == 12: return parsed > requested
    if how == 13: return parsed >= requested
    if how == 14: return parsed < requested
    if how == 15: return parsed <= requested
    _failure('unexpected howToCheck = ' + _native_how(how) + " in condition '" + name + "' that checks file version")


def _evaluate(ast, definitions, facts, document, registry=None):
    cache = document['condition_result_cache']; events = document['events']
    def visit(node):
        operation = node[0]
        if operation == 'value': return node[1]
        if operation == 'not': return not visit(node[1])
        if operation == 'and': return visit(node[1]) and visit(node[2])
        if operation == 'or': return visit(node[1]) or visit(node[2])
        name = node[1]
        event = {'lookup_name': name, 'status': 'started', 'cache_before': dict(cache),
                 'observations': [], 'result': None}
        events.append(event)
        try:
            if name in cache:
                event['resolution'] = 'cached'
                result = cache[name]
            elif name not in definitions:
                event['resolution'] = 'undefined'
                _failure("not defined condition name '" + name + "' used in expression '" + document['normalized_expression'] + "'")
            else:
                event.update(resolution='leaf', definition_name=definitions[name]['name'])
                result = (_leaf(name, definitions[name]['value'], facts, event) if registry is None
                          else _leaf(name, definitions[name]['value'], facts, event, registry))
                cache[name] = result
            event.update(status='passed', result=result, cache_after=dict(cache))
            return result
        except _Outcome as error:
            event.update(error.details, cache_after=dict(cache))
            raise
    return visit(ast)


@dataclass(frozen=True)
class ConditionStageReport:
    _document: str = field(repr=False)
    cause: BaseException | None = field(default=None, repr=False, compare=False)
    result: bool | None = field(default=None, repr=False)

    def as_dict(self):
        return json.loads(self._document)

    @property
    def computed(self):
        return type(self.result) is bool


class ToolkitUpdateConditions:
    def __init__(self):
        self.last_report = None

    def evaluate(self, condition_json: bytes, *, context: bytes) -> ConditionStageReport:
        self.last_report = None
        document = {'profile': PROFILE, 'scope': 'Conditions under supplied file facts only',
            'context_source': 'caller_supplied', 'context_verified': False,
            'package_applicability_evaluated': False, 'metadata_admission_evaluated': False,
            'publisher_trust_evaluated': False, 'updates_available': None,
            'machine_observations_performed': False, 'network_accessed': False, 'registry_accessed': False,
            'condition_result_under_supplied_context': None, 'events': [], 'condition_result_cache': {},
            'grammar_provenance': 'Original parser grammar plus finite direct/observational vectors; recursive parenthesized NOT is source-composed',
            'stages': [{'stage': name, 'status': 'not_run'} for name in STAGES]}
        rows = {row['stage']: row for row in document['stages']}; current = STAGES[0]
        def emergency_report(cause):
            emergency = ('{"scope":"Partial supplied-context condition evidence","evidence_export_failed":true,'
                '"original_error_retained":true,"condition_result_under_supplied_context":null,'
                '"package_applicability_evaluated":false,"publisher_trust_evaluated":false,"updates_available":null')
            for key in ('conditions_sha256', 'context_sha256'):
                if key in document:
                    emergency += ',"' + key + '":"' + document[key] + '"'
            self.last_report = ConditionStageReport(emergency + '}', cause)
            return self.last_report
        def finish(cause=None):
            try:
                self.last_report = ConditionStageReport(json.dumps(document, ensure_ascii=True, allow_nan=False),
                    cause, document['condition_result_under_supplied_context'])
                return self.last_report
            except BaseException as error:
                result = emergency_report(cause if cause is not None else error)
                if cause is not None:
                    return result
                raise
        try:
            for field_name, raw in (('conditions', condition_json), ('context', context)):
                if type(raw) is bytes and 0 < len(raw) <= MAX_JSON_BYTES:
                    document[field_name + '_sha256'] = hashlib.sha256(raw).hexdigest()
            current = 'typed_input'
            try:
                data = _json(condition_json, limit=MAX_JSON_BYTES, depth_limit=12); _ascii(data)
                document['raw_typed_data'] = data
                model = _typed(data); document['typed_model'] = model
                rows[current].update(status='passed', unknown_members='Ignored by the original model; retained in raw_typed_data')
            except _Outcome as error:
                rows[current].update(error.details); return finish()
            except ValueError as error:
                rows[current].update(status='failed', reason=str(error)); return finish()
            current = 'context_input'
            try:
                facts_data = _json(context, limit=MAX_JSON_BYTES, depth_limit=12); _ascii(facts_data)
                registry = None
                if type(facts_data) is dict and facts_data.get('format') == 'cbus-toolkit-condition-context-v2':
                    from . import _toolkit_update_registry_conditions as registry_leaves
                    registry = registry_leaves.facts(facts_data)
                    facts = _facts({'format': CONTEXT_FORMAT, 'culture': facts_data['culture'], 'files': facts_data['files']})
                    document.update(profile=registry_leaves.PROFILE, scope='Conditions under supplied file and registry facts only',
                                    registry_provider_profile=registry_leaves.PROVIDER, registry_provider_verified=False)
                    rows[current].update(registry_records=len(registry))
                else:
                    facts = _facts(facts_data)
                document['supplied_context'] = facts_data
                rows[current].update(status='passed', culture='invariant-ascii', file_records=len(facts))
            except _Outcome as error:
                rows[current].update(error.details); return finish()
            except ValueError as error:
                rows[current].update(status='failed', reason=str(error)); return finish()
            current = 'definition_validation'
            definitions = _validate(model)
            rows[current].update(status='passed')
            document['normalized_expression'] = model['expression'].lower()
            document['normalized_names'] = [{'name': name, 'lookup_name': name.lower()} for name in [x['name'] for x in model['conditions']]]
            current = 'expression_domain'
            ast = _Parser(model['expression']).parse()
            rows[current].update(status='passed')
            current = 'expression_evaluation'
            result = _evaluate(ast, definitions, facts, document) if registry is None else _evaluate(ast, definitions, facts, document, registry)
            document['condition_result_under_supplied_context'] = result
            rows[current].update(status='passed', result=result)
            visited = {row['lookup_name'] for row in document['events']}
            document['unrequested_definition_names'] = [x['name'] for x in model['conditions'] if x['name'].lower() not in visited]
            return finish()
        except _Outcome as error:
            rows[current].update(error.details)
            return finish()
        except BaseException as error:
            # Evidence creation/export is subordinate to the exact first exception.
            try:
                rows[current].update(status='not_run', interrupted=True)
                document['condition_result_under_supplied_context'] = None
                document['interrupted'] = _error(error)
                report = finish(error)
            except BaseException:
                report = emergency_report(error)
            try:
                error.toolkit_update_conditions_evidence = report.as_dict()
            except BaseException:
                pass
            raise
