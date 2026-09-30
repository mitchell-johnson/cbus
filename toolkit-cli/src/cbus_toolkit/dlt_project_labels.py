"""Preserving project TEXT labels for classic DLT groups and action selectors.

Toolkit's TGroupTagDLTCGateAgent stores LanguageID, FlavourID, TagType and
TagValue below a Group or Level's TagsDLT collection. These are shared project
records, not per-unit strings or a physical label-cache readback. This bounded
editor changes only explicitly selected TEXT variants and creates no groups,
actions, language definitions, PP data or hardware traffic.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from xml.dom import Node, minidom
from xml.parsers import expat
from xml.sax.saxutils import escape, quoteattr


PLAN_FORMAT = 'cbus-classic-dlt-project-text-plan-v1'
VIEW_FORMAT = 'cbus-classic-dlt-project-text-v1'
MAX_XML_BYTES = 16 * 1024 * 1024
MAX_TEXT_CHARACTERS = 1024  # Local workflow bound, not a display/wire limit.


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _children(node, name):
    return [child for child in node.childNodes if child.nodeType == Node.ELEMENT_NODE
            and child.namespaceURI is None and child.tagName == name]


def _one(node, name, *, required=True):
    rows = _children(node, name)
    if len(rows) > 1 or required and not rows:
        raise ValueError(f'Expected exactly one native {name} field')
    return rows[0] if rows else None


def _field(node, name, *, required=True):
    field = _one(node, name, required=required)
    if field is None:
        return None
    if any(child.nodeType == Node.ELEMENT_NODE for child in field.childNodes):
        raise ValueError(f'Native {name} field contains nested XML')
    return ''.join(child.data for child in field.childNodes
                   if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE))


def _byte(value, name, *, minimum=0, maximum=255):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in {minimum}..{maximum}')
    return value


def _stored_byte(value, name):
    if not isinstance(value, str) or re.fullmatch(r'0|[1-9][0-9]{0,2}', value) is None or int(value) > 255:
        raise ValueError(f'{name} must be a canonical decimal byte')
    return int(value)


def _path(target):
    if not isinstance(target, str):
        raise ValueError('DLT target must be a fully qualified group or action path')
    match = re.fullmatch(r'//([A-Za-z0-9_]{1,8})/(0|[1-9][0-9]{0,2})/(0|[1-9][0-9]{0,2})/(0|[1-9][0-9]{0,2})(?:/(0|[1-9][0-9]{0,2}))?', target)
    if not match:
        raise ValueError('Use //PROJECT/network/application/group[/action] for the DLT target')
    project = match[1]
    numbers = tuple(_stored_byte(value, 'DLT target address') for value in match.groups()[1:] if value is not None)
    application = numbers[1]
    if not (48 <= application <= 95 or application in (202, 203)):
        raise ValueError('DLT labels require a Lighting, Trigger Control or Enable application')
    if len(numbers) == 4 and application != 202:
        raise ValueError('Action-selector labels require Trigger Control application 202')
    return project, numbers


def _parse(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_XML_BYTES:
        raise ValueError('Native project XML must be text no larger than 16 MiB')
    checker = expat.ParserCreate()
    def reject(*_):
        raise ValueError('DTD/entity declarations are unsupported')
    checker.StartDoctypeDeclHandler = reject
    try:
        checker.Parse(text, True)
        document = minidom.parseString(text)
    except expat.ExpatError as error:
        raise ValueError('Invalid native project XML') from error
    root = document.documentElement
    if root.namespaceURI is not None or root.tagName not in ('Installation', 'Project'):
        raise ValueError('Expected native Installation or Project XML')
    return document


def _addressed(parent, kind, address):
    rows = [row for row in _children(parent, kind) if _field(row, 'Address') == str(address)]
    if len(rows) != 1:
        raise ValueError(f'Expected exactly one {kind} at address {address}')
    return rows[0]


def _target(document, target):
    project_name, numbers = _path(target)
    root = document.documentElement
    project = (_addressed(root, 'Project', project_name) if root.tagName == 'Installation' else root)
    if _field(project, 'Address') != project_name:
        raise ValueError('Project XML differs from the target project')
    network = _addressed(project, 'Network', numbers[0])
    application = _addressed(network, 'Application', numbers[1])
    group = _addressed(application, 'Group', numbers[2])
    node = group if len(numbers) == 3 else _addressed(group, 'Level', numbers[3])
    return network, node


def _tags(node):
    collection = _one(node, 'TagsDLT', required=False)
    rows = () if collection is None else _children(collection, 'TagDLT')
    if len(rows) > 8192:
        raise ValueError('Target exceeds the 8192 DLT tag workflow limit')
    return collection, rows


def _row(tag):
    return {'oid': _field(tag, 'OID', required=False),
            'language_id': _field(tag, 'LanguageID'), 'variant': _field(tag, 'FlavourID'),
            'tag_type': _field(tag, 'TagType'), 'text': _field(tag, 'TagValue')}


def _view(document, target):
    network, node = _target(document, target)
    _, tags = _tags(node)
    languages = _one(network, 'Languages', required=False)
    definitions = [] if languages is None else [
        {'language_id': _field(row, 'ID'), 'value': _field(row, 'TagValue')}
        for row in _children(languages, 'Language')]
    return {'format': VIEW_FORMAT, 'target': target, 'kind': node.tagName,
            'target_oid': _field(node, 'OID', required=False),
            'labels': [_row(tag) for tag in tags], 'network_languages': definitions,
            'language_definitions_changed': False, 'labels_transferred': False,
            'device_verified': False, 'label_text_in_unit': False}


def show_project_labels(text, target):
    """Read exact stored label fields, including non-TEXT types and language rows."""
    return {**_view(_parse(text), target), 'source_sha256': _hash(text)}


def _text(value):
    if not isinstance(value, str) or len(value) > MAX_TEXT_CHARACTERS:
        raise ValueError('Label text must be a string of at most 1024 characters (local workflow bound)')
    if any(ord(c) < 32 and c not in '\t\n\r' or 0xD800 <= ord(c) <= 0xDFFF
           or ord(c) in (0xFFFE, 0xFFFF) for c in value):
        raise ValueError('Label text contains characters forbidden by XML 1.0')
    return value


def _set(document, node, name, value):
    field = _one(node, name, required=False)
    if field is None:
        field = document.createElement(name)
        node.appendChild(field)
    _field(node, name)  # Refuse nested XML, retain attributes/comments/extensions.
    for child in list(field.childNodes):
        if child.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
            field.removeChild(child)
    field.appendChild(document.createTextNode(value))


def _serialize(node):
    # minidom emits attribute LF/TAB literally, losing them on reparse. quoteattr
    # emits references for all XML attribute whitespace; text CR also needs one.
    if node.nodeType == Node.DOCUMENT_NODE:
        return '<?xml version="1.0" ?>' + ''.join(_serialize(child) for child in node.childNodes)
    if node.nodeType == Node.ELEMENT_NODE:
        attrs = ''.join(' ' + name + '=' + quoteattr(value) for name, value in node.attributes.items())
        if not node.childNodes:
            return '<' + node.tagName + attrs + '/>'
        return ('<' + node.tagName + attrs + '>' + ''.join(_serialize(child) for child in node.childNodes)
                + '</' + node.tagName + '>')
    if node.nodeType == Node.TEXT_NODE:
        return escape(node.data).replace('\r', '&#13;')
    return node.toxml()


def _fragment(node):
    """Retain inherited namespace bindings when exposing a standalone snippet."""
    clone = node.cloneNode(deep=True)
    ancestor = node.parentNode
    while ancestor is not None and ancestor.nodeType == Node.ELEMENT_NODE:
        for name, value in ancestor.attributes.items():
            if (name == 'xmlns' or name.startswith('xmlns:')) and not clone.hasAttribute(name):
                clone.setAttribute(name, value)
        ancestor = ancestor.parentNode
    return _serialize(clone)


@dataclass(frozen=True)
class ProjectTextPlan:
    target: str
    source_sha256: str
    edits: tuple[tuple[int, int, str], ...]
    before: str
    after: str
    candidate_xml: str
    target_xml: str

    def as_dict(self):
        import json
        return {'format': PLAN_FORMAT, 'target': self.target, 'source_sha256': self.source_sha256,
                'edits': [{'language_id': language, 'variant': variant, 'text': value}
                          for language, variant, value in self.edits],
                'before': json.loads(self.before), 'after': json.loads(self.after),
                'candidate_sha256': _hash(self.candidate_xml),
                'target_xml': self.target_xml,
                'changed': self.before != self.after, 'saved': False,
                'labels_transferred': False, 'device_verified': False,
                'language_definitions_changed': False,
                'text_limit_basis': '1024-character local workflow bound; not a display or wire limit'}


def plan_project_labels(text, target, edits):
    """Plan one or more TEXT upserts, selected by numeric language and UI variant.

    Explicit blank text creates/retains a TEXT record. It does not remove a tag,
    clear a device cache or replace an image/font variant.
    """
    import json
    document = _parse(text)
    before = _view(document, target)
    _, node = _target(document, target)
    collection, tags = _tags(node)
    if not isinstance(edits, (list, tuple)) or not 1 <= len(edits) <= 1024:
        raise ValueError('Supply between one and 1024 explicit text edits')
    selected, prepared = set(), []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'language_id', 'variant', 'text'}:
            raise ValueError('Each text edit requires exactly language_id, variant and text')
        language = _byte(edit['language_id'], 'Language ID')
        variant = _byte(edit['variant'], 'Variant', minimum=1, maximum=4)
        value = _text(edit['text'])
        key = language, variant
        if key in selected:
            raise ValueError('A language/variant pair was selected more than once')
        selected.add(key)
        # Do not normalize malformed native records into addressable variants.
        # Reject numeric aliases of a selected identity (e.g. 01), too.
        matching = []
        for tag in tags:
            lang, flavour = _field(tag, 'LanguageID'), _field(tag, 'FlavourID')
            def aliases(raw, number):
                try:
                    return int(raw) == number
                except (TypeError, ValueError):
                    return False
            if aliases(lang, language) and aliases(flavour, variant):
                if lang != str(language) or flavour != str(variant):
                    raise ValueError('Selected DLT identity has a noncanonical numeric alias')
                matching.append(tag)
        if len(matching) > 1:
            raise ValueError('Selected language/variant has duplicate TagDLT records')
        if matching and _field(matching[0], 'TagType') != 'TEXT':
            raise ValueError('Selected DLT variant is not TEXT; image/font conversion is unsupported')
        prepared.append((language, variant, value, matching[0] if matching else None))
    normalized = tuple((language, variant, value) for language, variant, value, _ in prepared)
    changed = False
    for language, variant, value, tag in prepared:
        if tag is not None and _field(tag, 'TagValue') == value:
            continue
        changed = True
        if collection is None:
            collection = document.createElement('TagsDLT')
            node.appendChild(collection)
        if tag is None:
            tag = document.createElement('TagDLT')
            collection.appendChild(tag)
            for name, field in (('LanguageID', str(language)), ('FlavourID', str(variant)), ('TagType', 'TEXT')):
                _set(document, tag, name, field)
        _set(document, tag, 'TagValue', value)
    after = _view(document, target)
    candidate = _serialize(document) if changed else text
    if len(candidate.encode('utf-8')) > MAX_XML_BYTES:
        raise ValueError('Edited native project XML exceeds the 16 MiB workflow limit')
    return ProjectTextPlan(target, _hash(text), normalized,
                           json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True),
                           candidate, _fragment(node))


def apply_project_labels(text, plan):
    """Validate a saved plan against exact source bytes and re-derive its XML.

    Returns XML only. The caller owns exclusive output-file creation or a
    separately verified database save transaction.
    """
    if isinstance(plan, ProjectTextPlan):
        plan = plan.as_dict()
    if not isinstance(plan, dict) or plan.get('format') != PLAN_FORMAT:
        raise ValueError('Expected a ' + PLAN_FORMAT + ' document')
    if plan.get('source_sha256') != _hash(text):
        raise ValueError('Project XML changed since the DLT text plan was created')
    fresh = plan_project_labels(text, plan.get('target'), plan.get('edits'))
    if fresh.as_dict() != plan:
        raise ValueError('DLT text plan differs from its validated edits')
    return fresh.candidate_xml
