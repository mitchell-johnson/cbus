"""Preserving project transaction for the original predefined ICON dialog.

This bounded workflow covers the original visible predefined selector for
language 202. It models a fresh selected-language collection containing
TEXT/ICON records and one explicit built-in selection. It neither renders icons
nor programs physical labels or handles hidden historical selector states.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from .dlt_language_dialog import _aliases, _canonical, _prefix, _strict_target
from .dlt_project_labels import (MAX_XML_BYTES, _byte, _children, _field, _fragment,
                                 _hash, _one, _parse, _row, _serialize, _set,
                                 _stored_byte, _tags)


PLAN_FORMAT = 'cbus-classic-dlt-icon-dialog-plan-v1'
VIEW_FORMAT = 'cbus-classic-dlt-icon-dialog-v1'
CATALOGUE_FORMAT = 'cbus-classic-dlt-icon-catalogue-v1'
ICON_LANGUAGE = 202
BUILTIN_ICON_IDS = tuple(range(1, 92))
CATALOGUE_INDEX_SHA256 = 'c6cca64deaed7bb5ad814b2aaf4c37b580396bf38c057aae8bd616fadfd26310'


def catalogue():
    """Return admitted selection metadata, without redistributing icon assets."""
    return {'format': CATALOGUE_FORMAT, 'language_id': ICON_LANGUAGE,
            'icon_ids': list(BUILTIN_ICON_IDS), 'images_included': False,
            'original_index_sha256': CATALOGUE_INDEX_SHA256,
            'rendering_verified': False,
            'basis': 'Original selector stores the selected catalogue item Value as decimal text, not its combo-box index; bounded built-in IDs 1..91'}


def _language(network, language):
    _byte(language, 'Language ID', minimum=1)
    if language != ICON_LANGUAGE:
        raise ValueError('ICON transaction requires language 202 for the original visible predefined selector')
    collection = _one(network, 'Languages', required=False)
    matches = []
    for row in (() if collection is None else _children(collection, 'Language')):
        raw = _field(row, 'ID')
        if _aliases(raw, language):
            if raw != str(language):
                raise ValueError('Selected network language has a noncanonical ID alias')
            matches.append(row)
    if len(matches) != 1:
        raise ValueError('ICON dialog requires exactly one existing language 202 definition')
    return {'language_id': language, 'value': _field(matches[0], 'TagValue')}


def _selected(node, language):
    collection, tags = _tags(node)
    selected = {}
    for tag in tags:
        raw_language = _field(tag, 'LanguageID', required=False)
        if not _aliases(raw_language, language):
            continue
        if raw_language != str(language):
            raise ValueError('Selected DLT language has a noncanonical numeric alias')
        variant = _stored_byte(_field(tag, 'FlavourID'), 'Selected DLT flavour')
        if variant > 4:
            continue
        if variant in selected:
            raise ValueError('Selected language/flavour has duplicate TagDLT records')
        selected[variant] = tag
    active = {variant: selected.get(variant) for variant in range(1, 5)}
    if active[1] is None:
        active[1] = selected.get(0)
    for variant, tag in active.items():
        if tag is not None and _field(tag, 'TagType') not in ('TEXT', 'ICON'):
            raise ValueError(f'Selected language flavour {variant} is not canonical TEXT or ICON; FONT/DYNAMIC and unknown transitions are unsupported')
    return collection, active


def _initialize(document, target, language):
    network, node = _strict_target(document, target)
    definition = _language(network, language)
    collection, active = _selected(node, language)
    flavours, normalizations = [], []
    for variant in range(1, 5):
        tag = active[variant]
        stored = None if tag is None else _row(tag)
        if tag is not None:
            kind, value = stored['tag_type'], _prefix(stored['text'], f'Existing flavour {variant}')
            provenance = 'saved-exact-flavour' if stored['variant'] == str(variant) else 'saved-legacy-flavour-0'
            if value != stored['text']:
                normalizations.append({'variant': variant, 'operation': 'truncate-non-FONT-value',
                                       'before': stored['text'], 'after': value})
        elif variant == 1:
            kind, value, provenance = 'ICON', '', 'fresh-language-202-first-flavour-ICON-empty'
        else:
            kind, value, provenance = None, None, 'missing-alternate-removed-from-fresh-cache'
        flavours.append({'variant': variant, 'present': tag is not None or variant == 1,
                         'tag_type': kind, 'text': value, 'stored': stored,
                         'initialization_provenance': provenance})
    view = {'format': VIEW_FORMAT, 'target': target, 'kind': node.tagName,
            'target_oid': _field(node, 'OID', required=False), 'source_sha256': None,
            'language': definition, 'flavours': flavours, 'catalogue': catalogue(),
            'initialization_normalizations': normalizations,
            'scope': {'fresh_collection': True, 'selected_language_only': True,
                      'missing_alternates_preserved_on_initialize': False,
                      'finalise_supplied_model': None, 'source_tag_type_scope': ['TEXT', 'ICON'],
                      'owner_default_representation_consumed': False},
            'language_definitions_changed': False, 'labels_transferred': False,
            'device_verified': False, 'original_full_dialog_executed': False}
    return node, collection, active, view


def show_icon_dialog(text, target, language):
    """Inspect fresh ICON-dialog state without persisting normalization."""
    _, _, _, view = _initialize(_parse(text), target, language)
    view['source_sha256'] = _hash(text)
    return view


@dataclass(frozen=True)
class DltIconDialogPlan:
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


def plan_icon_dialog(text, target, language, variant, icon_id):
    """Select one original built-in icon and finalize the selected language."""
    _byte(variant, 'Variant', minimum=1, maximum=4)
    _byte(icon_id, 'Built-in icon ID', minimum=1, maximum=91)
    document = _parse(text)
    node, collection, active, before = _initialize(document, target, language)
    before['source_sha256'] = _hash(text)
    final = [{'variant': row['variant'], 'present': row['present'],
              'tag_type': row['tag_type'], 'text': row['text']} for row in before['flavours']]
    final[variant - 1].update(present=True, tag_type='ICON', text=str(icon_id))
    effects = []
    for row in final:
        flavour, kind, content = row['variant'], row['tag_type'], row['text']
        tag = active[flavour]
        previous = None if tag is None else _row(tag)
        operation = 'preserve'
        if row['present']:
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
                                           ('TagType', kind), ('TagValue', content)):
                    _set(document, tag, field, field_value)
            elif previous['tag_type'] != kind or previous['text'] != content:
                operation = 'update'
                if previous['tag_type'] != kind:
                    _set(document, tag, 'TagType', kind)
                if previous['text'] != content:
                    _set(document, tag, 'TagValue', content)
        effects.append({'variant': flavour, 'operation': operation, 'before': previous,
                        'after': None if tag is None else _row(tag),
                        'cause': 'explicit-builtin-ICON-action' if flavour == variant else 'selected-language-finalization'})
    changed = any(row['operation'] != 'preserve' for row in effects)
    candidate = _serialize(document) if changed else text
    if len(candidate.encode('utf-8')) > MAX_XML_BYTES:
        raise ValueError('Edited native project XML exceeds the 16 MiB workflow limit')
    payload = {'format': PLAN_FORMAT, 'target': target, 'source_sha256': _hash(text),
               'requested': {'language': language, 'variant': variant, 'icon_id': icon_id},
               'before': before, 'dialog_after': final, 'effects': effects,
               'catalogue': catalogue(), 'candidate_sha256': _hash(candidate),
               'target_xml': _fragment(node), 'changed': changed,
               'saved': False, 'labels_transferred': False, 'device_verified': False,
               'rendering_verified': False, 'language_definitions_changed': False,
               'original_full_dialog_executed': False,
               'encoding_boundary': 'Original non-FONT initialization retains 20 UTF-16 units; refuse split surrogate pairs',
               'finalization': {'selected_language': language, 'supplied_model': None,
                                'flavours_in_order': [1, 2, 3, 4], 'empty_value_deletes': True,
                                'legacy_flavour_0_identity_preserved': True,
                                'per_flavour_type_preserved_unless_explicitly_edited': True}}
    return DltIconDialogPlan(_canonical(payload), candidate)


def apply_icon_dialog(text, plan):
    """Re-derive the complete reviewed transaction against exact source XML."""
    if isinstance(plan, DltIconDialogPlan):
        plan = plan.as_dict()
    if not isinstance(plan, dict) or plan.get('format') != PLAN_FORMAT:
        raise ValueError('Expected a ' + PLAN_FORMAT + ' document')
    if plan.get('source_sha256') != _hash(text):
        raise ValueError('Project XML changed since the DLT ICON-dialog plan was created')
    request = plan.get('requested')
    if not isinstance(request, dict) or set(request) != {'language', 'variant', 'icon_id'}:
        raise ValueError('Invalid DLT ICON-dialog request')
    fresh = plan_icon_dialog(text, plan.get('target'), request['language'], request['variant'], request['icon_id'])
    try:
        matches = _canonical(fresh.as_dict()) == _canonical(plan)
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid canonical DLT ICON-dialog plan') from error
    if not matches:
        raise ValueError('DLT ICON-dialog plan differs from its canonical source-derived action')
    return fresh.candidate_xml
