"""Owner-issued text-only Language XML refresh for retained scene labels.

The bridge proves a Language-only projection.  It is not a serialized cache,
an automatic event scheduler or a reproduction of the original per-row saves.
The shared native resolver remains responsible for causal object creation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json

from .edlt import EdltError


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise EdltError('Invalid scene Language initializer binding') from error


def _sha(text):
    if type(text) is not str:
        raise EdltError('Scene Language initializer requires exact XML strings')
    try:
        return hashlib.sha256(text.encode('utf8')).hexdigest()
    except UnicodeError as error:
        raise EdltError('Scene Language XML contains invalid Unicode') from error


class _Seal:
    def __init__(self, owner):
        self.owner = owner
        self.fingerprint = None


@dataclass(frozen=True)
class SceneLanguageInitializer:
    """Nonserialized proof; old labels retain their actual issued identities."""
    original_timeline: object
    original_label_template: tuple
    projected_label_template: tuple
    refresh_count: int
    _binding: str
    _seal: _Seal

    @property
    def initial_scene_bindings(self):
        check_language_initializer(self)
        return self.original_timeline._initial_scene_bindings

    def initial_scene_labels(self, slot):
        check_language_initializer(self)
        cursor = self.original_timeline.start(self.original_timeline._template,
            source_values=json.loads(self.original_timeline._source_values),
            owner=self._seal.owner)
        return cursor.initial_scene_labels(slot)

    def timeline_labels(self, *, current_generation, current_template):
        """Return epoch facts and exact old object seeds for native issuance.

        The resolver supplies its complete current template, including genuine
        prior creations. Its observed Language-derived rows must be exact.
        """
        check_language_initializer(self)
        old = self.original_timeline
        if (type(current_generation) is not int
                or current_generation < old._initial.refresh_generation + self.refresh_count):
            raise EdltError('Language refresh generation precedes original initialization')
        observed = {(row.group, row.action): row.as_dict()
                    for row in self.projected_label_template}
        supplied = {(row.group, row.action): row.as_dict() for row in current_template}
        if (any(observed[key] != row for key, row in supplied.items() if key in observed)
                or any(label['name'] or label['image_present']
                       for key, row in supplied.items() if key not in observed
                       for label in row['labels'])):
            raise EdltError('Current native labels differ from the issued Language projection')
        # Do not inherit hypothetical terminal/validation generations from the
        # initializer's own plan. Only its actual initial loader is prior state.
        maximum = old._initial.refresh_generation
        old_epochs = []
        originals = {(row.group, row.action): row for row in self.original_label_template}
        for generation, rows in old._label_epochs:
            if generation > maximum:
                continue
            keys = {(row.group, row.action) for row in rows}
            added = []
            for row in current_template:
                key = (row.group, row.action)
                if key in keys:
                    continue
                original = originals.get(key)
                if original is None and any(label.name or label.image_present for label in row.labels):
                    raise EdltError('New causal Levels require source-established blank defaults')
                # A previously unconsumed but observed Level already had old
                # Language facts. Its labels cannot borrow the new default.
                added.append(row if original is None else original)
            old_epochs.append((generation, (*rows, *added)))
        old_epochs = tuple(old_epochs)
        epochs = (*old_epochs, (current_generation, tuple(current_template)))
        if not self.refresh_count and current_generation == maximum:
            # No Language refresh happened. Preserve old epochs/objects, but
            # allow the final template to contain later causal creations.
            epochs = tuple((generation, tuple(current_template))
                           if generation == maximum else (generation, rows)
                           for generation, rows in old_epochs)
            if epochs[-1][0] != maximum:
                epochs = (*epochs, (maximum, tuple(current_template)))
        seeds = []
        for generation in sorted({maximum, *(row[2] for row in old._initial_scene_bindings)}):
            original = old.labels_at(generation)
            expected = next(rows for start, rows in reversed(epochs) if start <= generation)
            # Extend old template with blank newly created objects while
            # retaining exact original DataStore objects for observed owners.
            present = {(row.group, row.action): row for row in original}
            seed = tuple(present.get((row.group, row.action), row) for row in expected)
            if [row.as_dict() for row in seed] != [row.as_dict() for row in expected]:
                raise EdltError('Language refresh would rewrite an original label epoch')
            seeds.append((generation, seed))
        return tuple(epochs), tuple(seeds)

    @property
    def fingerprint(self):
        payload = {'binding': json.loads(self._binding),
                   'original_timeline_sha256': self.original_timeline.fingerprint,
                   'initial_scene_bindings': self.original_timeline._initial_scene_bindings,
                   'original_label_template': [row.as_dict() for row in self.original_label_template],
                   'projected_label_template': [row.as_dict() for row in self.projected_label_template],
                   'refresh_count': self.refresh_count}
        return hashlib.sha256(_json(payload).encode('ascii')).hexdigest()

    def as_dict(self):
        check_language_initializer(self)
        return {'format': 'cbus-edlt-scene-language-initializer-v1',
                'sha256': self.fingerprint, 'binding': json.loads(self._binding),
                'original_timeline_sha256': self.original_timeline.fingerprint,
                'initial_scene_bindings': [list(row) for row in self.initial_scene_bindings],
                'original_label_template': [row.as_dict() for row in self.original_label_template],
                'projected_label_template': [row.as_dict() for row in self.projected_label_template],
                'refresh_count': self.refresh_count,
                'refresh_profile': 'explicit-final-text-only-Language-XML-refresh',
                'serialized_input_capability': False, 'original_execution': False,
                'implicit_notifications_inferred': False, 'database_execution': False}


def check_language_initializer(value, *, original_xml=None, projected_xml=None,
                               unit=None, editor=None, original_values=None):
    from .edlt_scene_inventory_timeline import check_timeline
    if type(value) is not SceneLanguageInitializer or type(value._seal) is not _Seal:
        raise EdltError('Scene Language initializer is foreign or serialized')
    owner = None if editor is None else editor._owner
    check_timeline(value.original_timeline, owner=value._seal.owner)
    if (owner is not None and owner is not value._seal.owner
            or value._seal.fingerprint != value.fingerprint):
        raise EdltError('Scene Language initializer is foreign or modified')
    binding = json.loads(value._binding)
    from .edlt_parent_metadata import _unit_path
    if (original_xml is not None and _sha(original_xml) != binding['original_xml_sha256']
            or projected_xml is not None and _sha(projected_xml) != binding['projected_xml_sha256']
            or unit is not None and _unit_path(unit)[0] != binding['unit']):
        raise EdltError('Scene Language initializer XML/unit provenance differs')
    if original_values is not None:
        if editor is None:
            raise EdltError('Scene Language PP validation requires its owning editor')
        if _json(editor.snapshot(original_values)) != value.original_timeline._source_values:
            raise EdltError('Scene Language initializer original PP differs')
    return value


def _text_only(text, unit):
    """Refuse unresolved image profiles across the selected Network refresh."""
    from .edlt_parent_metadata import _container, _children, _one_by_address, _unit_path, _field
    document = _container(text, 'Installation')
    project = _children(document.documentElement, 'Project')[0]
    network = _one_by_address(project, 'Network', _unit_path(unit)[2])
    for node in network.getElementsByTagName('*'):
        if node.tagName in ('Image', 'Images', 'ProjectImages', 'DLTP'):
            raise EdltError('Scene Language initializer excludes Image/DLTP metadata')
        if node.tagName == 'TagDLT' and _field(node, 'TagType') not in ('', 'TEXT'):
            raise EdltError('Scene Language initializer requires text-only TagDLT metadata')


def _facts(snapshot):
    images = [{'application': app.address, 'group': group.address,
               'known': group.dynamic_images_known,
               'images': None if group.dynamic_images is None else list(group.dynamic_images)}
              for app in snapshot.applications for group in app.groups]
    labels = [{'group': group.address, 'action': level.address,
               'labels': None if not level.dynamic_labels_known else [
                   {'value': variant, 'name': name, 'image_present': image}
                   for variant, name, image in level.dynamic_labels]}
              for app in snapshot.applications if app.address == 202
              for group in app.groups for level in group.level_records]
    return images, labels


def issue_language_initializer(initializer, *, original_xml, projected_xml,
                               unit, editor, original_values, operations, mutations):
    """Independently reproject an exact parent-history prefix through Language.

    ``operations`` is the public history prefix, ending at the current Language
    operation. ``mutations`` contains its exact internal native bindings, in
    that order. Raw mappings cannot supply receipt authority. No I/O occurs.
    """
    from .edlt_scene_inventory_timeline import check_timeline
    from .edlt_scene_manager import EdltSceneManager, SceneDynamicLabel, SceneLevelLabels
    from .edlt_parent_metadata import _snapshot, _unit_path, _default_language, _container, _children, _one_by_address
    from .edlt_parent_transaction import _NativeLanguageBinding
    from .edlt_language_add_dialog import (LanguageRow, native_inventory, initialise,
        normalize, project, replace_native_rows, _preferences)
    if type(editor) is not EdltSceneManager:
        raise EdltError('Scene Language initializer requires its original scene editor')
    check_timeline(initializer, owner=editor._owner)
    unit = _unit_path(unit)[0]
    source_binding = json.loads(initializer._binding)
    if (source_binding.get('unit') != unit
            or source_binding.get('source_xml_sha256') != _sha(original_xml)):
        raise EdltError('Scene Language initializer original XML/unit differs')
    if _json(editor.snapshot(original_values)) != initializer._source_values:
        raise EdltError('Scene Language initializer original PP differs')
    if (type(operations) not in (tuple, list) or not 1 <= len(operations) <= 256
            or any(type(row) is not dict for row in operations)
            or operations[-1].get('op') != 'add-language-dialog'
            or type(mutations) is not tuple
            or any(type(row) is not _NativeLanguageBinding for row in mutations)):
        raise EdltError('Scene Language initializer requires the exact typed Language history prefix')
    history = tuple((index, normalize(row)) for index, row in enumerate(operations, 1)
                    if row.get('op') == 'add-language-dialog')
    if len(history) != len(mutations) or not history:
        raise EdltError('Scene Language initializer receipt/history counts differ')
    _text_only(original_xml, unit)
    _text_only(projected_xml, unit)
    # Do not broaden duplicate/default/lexical-ID native metadata admission.
    baseline = _snapshot(original_xml, unit, editor)
    current = _snapshot(projected_xml, unit, editor)
    if (baseline.value_map() != current.value_map()
            or baseline.raw_map() != current.raw_map()):
        raise EdltError('Language-only XML projection changed original PP')
    _network, collection, rows = native_inventory(original_xml, unit)
    first = history[0][1]
    state = initialise(rows, first['preferences'])
    # The managed loaded default, not a stale native process default, owns the
    # original scene labels. Refuse a preference/default disagreement.
    root = _container(original_xml, 'Installation').documentElement
    selected_network = _one_by_address(_children(root, 'Project')[0], 'Network', _unit_path(unit)[2])
    if state.default != _default_language(selected_network):
        raise EdltError('Language preferences differ from the original loaded default')
    next_key = 0
    projected = original_xml
    receipts = []
    for (index, operation), supplied in zip(history, mutations):
        if _preferences(operation['preferences']) != _preferences(first['preferences']):
            raise EdltError('Scene Language history changes its preference profile')
        state, receipt = project(state, operation)
        for identifier in [row.identifier for row in state.rows if row.oid is None]:
            key = '@language-' + str(next_key)
            next_key += 1
            state = replace(state, rows=tuple(replace(row, oid=key)
                if row.oid is None and row.identifier == identifier else row for row in state.rows))
            for row in receipt['created_rows']:
                if row['oid'] is None and row['id'] == identifier:
                    row['oid'] = key
        receipt['rows_after'] = [row.as_dict() for row in state.rows]
        receipt['operation'] = index
        # Cancellation never manufactures a Languages collection.
        projected = (original_xml if all(row['cancelled'] for row in (*receipts, receipt)) else
                     replace_native_rows(original_xml, unit, state.rows,
                         collection_oid=collection or '@languages'))
        step = _snapshot(projected, unit, editor)
        images, labels = _facts(step)
        if dict(supplied) != {'op': 'parent-language-binding', 'receipt': receipt,
                            'group_images': images, 'level_labels': labels}:
            raise EdltError('Scene Language mutation receipt is not the exact source reprojection')
        receipts.append(receipt)
    # Byte comparison binds the deterministic projection, including comments,
    # opaque/namespaced nodes and whitespace, not a lossy generic XML shape.
    equivalent_original = state.rows == rows and projected_xml == original_xml
    if projected_xml != projected and not equivalent_original:
        raise EdltError('Scene Language projection changed unrelated XML or row provenance')
    images, labels = _facts(current)
    if any(not row['known'] or any(row['images']) for row in images):
        raise EdltError('Scene Language initializer contains unknown/image facts')
    template = [SceneLevelLabels(row['group'], row['action'], tuple(
        SceneDynamicLabel(**label) for label in row['labels'])) for row in labels]
    _old_images, original_labels = _facts(baseline)
    original_template = tuple(SceneLevelLabels(row['group'], row['action'], tuple(
        SceneDynamicLabel(**label) for label in row['labels'])) for row in original_labels)
    existing = {(row.group, row.action) for row in template}
    # Initial getter-created Levels may not yet exist in the native XML. Only
    # the original initializer's proven creations authorize their blank rows.
    initialized_levels = {(group, action) for app, group, actions in initializer._initial.levels
                          if app == 202 for action in actions}
    for row in initializer._template.level_labels:
        if (row.group, row.action) not in existing and (row.group, row.action) in initialized_levels:
            if any(label.name or label.image_present for label in row.labels):
                raise EdltError('Unstored initialized Level has nonblank label facts')
            template.append(replace(row, labels=tuple(replace(label) for label in row.labels)))
    changed = state.rows != rows
    binding = {'unit': unit, 'original_xml_sha256': _sha(original_xml),
               'projected_xml_sha256': _sha(projected_xml),
               'history_prefix_sha256': hashlib.sha256(_json(operations).encode('ascii')).hexdigest(),
               'history_prefix_operations': len(operations),
               'original_pp_sha256': hashlib.sha256(initializer._source_values.encode('ascii')).hexdigest(),
               'language_receipts': receipts, 'text_only': True,
               'default_before': initialise(rows, first['preferences']).default,
               'default_after': state.default}
    value = SceneLanguageInitializer(initializer, original_template, tuple(template), int(changed),
                                     _json(binding), _Seal(editor._owner))
    value._seal.fingerprint = value.fingerprint
    return value
