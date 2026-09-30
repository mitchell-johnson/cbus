"""Bounded classic DLT TEXT-dialog initialization, action and finalization.

This is deliberately distinct from the exact project TEXT editor. It models a
fresh TEXT-only language collection and flushes the selected language's four
flavours after one original TEXT action. Saved project records are the input;
network language preferences, warmed caches and physical labels are not guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from .dlt_project_labels import (MAX_XML_BYTES, _byte, _children, _field, _fragment,
                                 _hash, _one, _parse, _path, _row, _serialize, _set,
                                 _stored_byte, _tags, _target, _text)

PLAN_FORMAT = 'cbus-classic-dlt-language-dialog-plan-v1'
VIEW_FORMAT = 'cbus-classic-dlt-language-dialog-v1'
# Pinned Toolkit factory entries. ID 0 is the default marker; 202 is ICON-only.
TEXT_LANGUAGE_IDS = frozenset((*range(1, 15), *range(64, 117)))
UTF16_LIMIT = 20


def _canonical(value):
    """Retain JSON type distinctions, including bool versus int, on replay."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':'))


def _aliases(raw, value):
    try:
        return int(raw) == value
    except (TypeError, ValueError):
        return False


def _strict_target(document, target):
    """Refuse numerical aliases along the selected native address path."""
    network, node = _target(document, target)
    _, addresses = _path(target)
    current = network
    chain = [('Network', addresses[0], network.parentNode),
             ('Application', addresses[1], network)]
    for kind, address, parent in chain:
        for sibling in _children(parent, kind):
            raw = _field(sibling, 'Address')
            if _aliases(raw, address) and raw != str(address):
                raise ValueError('Selected DLT target has a noncanonical address alias')
        current = next(row for row in _children(parent, kind) if _field(row, 'Address') == str(address))
    for kind, address in zip(('Group', 'Level'), addresses[2:]):
        for sibling in _children(current, kind):
            raw = _field(sibling, 'Address')
            if _aliases(raw, address) and raw != str(address):
                raise ValueError('Selected DLT target has a noncanonical address alias')
        current = next(row for row in _children(current, kind) if _field(row, 'Address') == str(address))
    return network, node


def _language(network, language):
    _byte(language, 'Language ID', minimum=1)
    if language not in TEXT_LANGUAGE_IDS:
        raise ValueError('TEXT dialog requires a supported text-language ID (1..14 or 64..116); ID 202 is ICON-only')
    collection = _one(network, 'Languages', required=False)
    matches = []
    for row in (() if collection is None else _children(collection, 'Language')):
        raw = _field(row, 'ID')
        if _aliases(raw, language):
            if raw != str(language):
                raise ValueError('Selected network language has a noncanonical ID alias')
            matches.append(row)
    if len(matches) != 1:
        raise ValueError('TEXT dialog requires exactly one existing selected network language definition')
    return {'language_id': language, 'value': _field(matches[0], 'TagValue')}


def _prefix(value, description):
    """Original UStrCopy uses UTF-16 units; XML cannot hold a split pair."""
    raw = value.encode('utf-16-le')
    try:
        result = raw[:UTF16_LIMIT * 2].decode('utf-16-le')
    except UnicodeDecodeError as error:
        raise ValueError(description + ': original 20-UTF-16-unit prefix splits a surrogate pair; XML output is unsupported') from error
    return result


def _selected(node, language):
    collection, tags = _tags(node)
    selected = {}
    for tag in tags:
        raw_language = _field(tag, 'LanguageID', required=False)
        if not _aliases(raw_language, language):
            continue
        if raw_language != str(language):
            raise ValueError('Selected DLT language has a noncanonical numeric alias')
        raw_variant = _field(tag, 'FlavourID')
        variant = _stored_byte(raw_variant, 'Selected DLT flavour')
        if variant > 4:
            continue  # Original FinaliseLanguage visits only UI flavours 1..4.
        if variant in selected:
            raise ValueError('Selected language/flavour has duplicate TagDLT records')
        selected[variant] = tag
    active = {variant: selected.get(variant) for variant in range(1, 5)}
    if active[1] is None:
        active[1] = selected.get(0)
    for variant, tag in active.items():
        if tag is not None and _field(tag, 'TagType') != 'TEXT':
            raise ValueError(f'Selected language flavour {variant} is not TEXT; warmed-cache and image/font transitions are unsupported')
    return collection, active


def _initialize(document, target, language, owner_default_representation):
    network, node = _strict_target(document, target)
    definition = _language(network, language)
    collection, active = _selected(node, language)
    if owner_default_representation is not None:
        _text(owner_default_representation)
    flavours, normalizations = [], []
    for variant in range(1, 5):
        tag = active[variant]
        stored = None if tag is None else _row(tag)
        if tag is not None:
            value = _prefix(stored['text'], f'Existing flavour {variant}')
            provenance = 'saved-exact-flavour' if stored['variant'] == str(variant) else 'saved-legacy-flavour-0'
            if value != stored['text']:
                normalizations.append({'variant': variant, 'operation': 'truncate-text',
                                       'before': stored['text'], 'after': value})
        elif variant == 1:
            value = (None if owner_default_representation is None else
                     _prefix(owner_default_representation, 'Owner default representation'))
            provenance = ('unobserved-owner-default-representation' if value is None else
                          'caller-supplied-owner-default-representation')
        else:
            value, provenance = None, 'missing-alternate-removed-from-fresh-cache'
        flavours.append({'variant': variant, 'present': tag is not None or variant == 1,
                         'text': value, 'tag_type': 'TEXT', 'stored': stored,
                         'initialization_provenance': provenance})
    view = {'format': VIEW_FORMAT, 'target': target, 'kind': node.tagName,
            'target_oid': _field(node, 'OID', required=False), 'source_sha256': None,
            'language': definition, 'flavours': flavours,
            'default_representation_required': active[1] is None and owner_default_representation is None,
            'initialization_normalizations': normalizations,
            'scope': {'fresh_collection': True, 'selected_language_only': True,
                      'missing_alternates_preserved_on_initialize': False,
                      'finalise_supplied_model': None, 'source_tag_type_scope': 'TEXT'},
            'language_definitions_changed': False, 'labels_transferred': False,
            'device_verified': False, 'original_full_dialog_executed': False}
    return node, collection, active, view


def show_language_dialog(text, target, language, *, owner_default_representation=None):
    """Inspect the admitted fresh dialog state, without saving normalization."""
    _, _, _, view = _initialize(_parse(text), target, language, owner_default_representation)
    view['source_sha256'] = _hash(text)
    return view


@dataclass(frozen=True)
class DltLanguageDialogPlan:
    """Immutable canonical metadata and its derived candidate document."""
    _json: str
    candidate_xml: str

    def as_dict(self):
        return json.loads(self._json)

    @property
    def target_xml(self):
        return self.as_dict()['target_xml']

    @property
    def source_sha256(self):
        return self.as_dict()['source_sha256']

    @property
    def target(self):
        return self.as_dict()['target']


def plan_language_dialog(text, target, language, variant, value, *,
                         confirm_non_latin1=False, owner_default_representation=None):
    """Plan one TEXT button action and finalization of all selected flavours.

    Empty input is the original literal ``<Default>``. A missing first flavour
    needs the caller's exact owner display representation unless this very
    action overwrites flavour 1, making that temporary default irrelevant.
    """
    _byte(variant, 'Variant', minimum=1, maximum=4)
    _text(value)
    if type(confirm_non_latin1) is not bool:
        raise ValueError('confirm_non_latin1 must be a boolean')
    needs_confirmation = any(ord(character) > 255 for character in value)
    if needs_confirmation and not confirm_non_latin1:
        raise ValueError('Original TEXT dialog requires confirmation for non-Latin-1 input, including text beyond the 20-unit prefix')
    action_value = '<Default>' if value == '' else _prefix(value, 'Explicit TEXT input')
    document = _parse(text)
    node, collection, active, before = _initialize(document, target, language, owner_default_representation)
    before['source_sha256'] = _hash(text)
    if before['default_representation_required'] and variant != 1:
        raise ValueError('Missing first flavour requires owner_default_representation; XML cannot establish the original display-format preference')
    final = [{'variant': row['variant'], 'present': row['present'], 'text': row['text'],
              'tag_type': 'TEXT'} for row in before['flavours']]
    final[variant - 1].update(present=True, text=action_value)
    effects = []
    for row in final:
        flavour, content = row['variant'], row['text']
        tag = active[flavour]
        previous = None if tag is None else _row(tag)
        operation = 'preserve'
        if row['present']:
            if content is None:
                raise ValueError('Unresolved original first-flavour default cannot be finalized')
            if content == '':
                if tag is not None:
                    operation = 'delete'
                    collection.removeChild(tag)
                    tag = None
            elif tag is None:
                operation = 'create'
                if collection is None:
                    collection = document.createElement('TagsDLT')
                    node.appendChild(collection)
                tag = document.createElement('TagDLT')
                collection.appendChild(tag)
                for field, field_value in (('LanguageID', str(language)), ('FlavourID', str(flavour)),
                                           ('TagType', 'TEXT'), ('TagValue', content)):
                    _set(document, tag, field, field_value)
            elif previous['text'] != content:
                operation = 'update'
                _set(document, tag, 'TagValue', content)
        effects.append({'variant': flavour, 'operation': operation, 'before': previous,
                        'after': None if tag is None else _row(tag),
                        'cause': 'explicit-TEXT-action' if flavour == variant else 'selected-language-finalization'})
    changed = any(effect['operation'] != 'preserve' for effect in effects)
    candidate = _serialize(document) if changed else text
    if len(candidate.encode('utf-8')) > MAX_XML_BYTES:
        raise ValueError('Edited native project XML exceeds the 16 MiB workflow limit')
    payload = {'format': PLAN_FORMAT, 'target': target, 'source_sha256': _hash(text),
               'requested': {'language': language, 'variant': variant, 'text': value,
                             'confirm_non_latin1': confirm_non_latin1,
                             'owner_default_representation': owner_default_representation},
               'before': before, 'dialog_after': final, 'effects': effects,
               'input_confirmation': {'non_latin1_found_before_truncation': needs_confirmation,
                                      'confirmed': confirm_non_latin1},
               'unobserved_default_overwritten': before['default_representation_required'] and variant == 1,
               'default_representation_provenance': ('not-supplied' if owner_default_representation is None else
                                                     'caller-supplied; source XML cannot establish display preference'),
               'candidate_sha256': _hash(candidate), 'target_xml': _fragment(node),
               'changed': changed, 'saved': False, 'labels_transferred': False,
               'device_verified': False, 'language_definitions_changed': False,
               'original_full_dialog_executed': False,
               'text_limit_basis': 'Original TEXT button and non-FONT initialization retain at most 20 UTF-16 code units',
               'encoding_boundary': 'Refuse prefixes containing split surrogate pairs; no invented XML replacement',
               'finalization': {'selected_language': language, 'supplied_model': None,
                                'flavours_in_order': [1, 2, 3, 4], 'empty_value_deletes': True,
                                'legacy_flavour_0_identity_preserved': True}}
    return DltLanguageDialogPlan(_canonical(payload), candidate)


def apply_language_dialog(text, plan):
    """Re-derive a canonical plan against its exact XML source; return XML only."""
    if isinstance(plan, DltLanguageDialogPlan):
        plan = plan.as_dict()
    if not isinstance(plan, dict) or plan.get('format') != PLAN_FORMAT:
        raise ValueError('Expected a ' + PLAN_FORMAT + ' document')
    if plan.get('source_sha256') != _hash(text):
        raise ValueError('Project XML changed since the DLT text-dialog plan was created')
    request = plan.get('requested')
    if not isinstance(request, dict) or set(request) != {
            'language', 'variant', 'text', 'confirm_non_latin1', 'owner_default_representation'}:
        raise ValueError('Invalid DLT text-dialog request')
    fresh = plan_language_dialog(text, plan.get('target'), request['language'], request['variant'], request['text'],
                                confirm_non_latin1=request['confirm_non_latin1'],
                                owner_default_representation=request['owner_default_representation'])
    try:
        matches = _canonical(fresh.as_dict()) == _canonical(plan)
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid canonical DLT text-dialog plan') from error
    if not matches:
        raise ValueError('DLT text-dialog plan differs from its canonical source-derived action')
    return fresh.candidate_xml
