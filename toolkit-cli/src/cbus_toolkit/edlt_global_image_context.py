"""Issued image-aware source facts for the ordinary Global Programming model.

The input is one complete native project document. Image exports are explicit
byte-backed providers. This projection does not create applications/groups,
load destination models, transfer labels, upload images or initialize a factory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import weakref
from xml.dom import Node

from .edlt import EdltError
from .edlt_lifecycle import LifecycleCache, LifecycleGroup
from .edlt_parent_metadata import (_snapshot, _unit_path, _default_language,
    _children, _field, _byte, _one_by_address)
from .edlt_scene_label_images import (check_project_images, check_dltp_images,
    DecodedDltpImages)
from .addressing import _container


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(value.encode('utf-8') if type(value) is str else value).hexdigest()


class _Seal:
    __slots__ = ('__weakref__',)


_ISSUED = weakref.WeakKeyDictionary()


def _provider(value, *, project=None):
    if value is None:
        return None
    if project is not None:
        check_project_images(value, project=project)
    else:
        check_dltp_images(value)
    return value.evidence()


def _project_node(text, project):
    root = _container(text, 'Installation').documentElement
    projects = _children(root, 'Project')
    if root.tagName != 'Installation' or len(projects) != 1:
        raise EdltError('Global image context requires one complete Installation/Project')
    if _field(projects[0], 'Address') != project:
        raise EdltError('Global image context project identity differs')
    return root, projects[0]


def project_graph(text, project, *, mutable_parameters=()):
    """Canonical whole graph, excluding only explicitly allowed target PP values.

    Text leaves, opaque attributes, element order and comments are retained.
    Formatting whitespace between elements is ignored; xml:space preservation
    and a general native repository normalization contract are not inferred.
    """
    root, project_node = _project_node(text, project)
    allowed = dict(mutable_parameters)
    if len(allowed) != len(mutable_parameters):
        raise EdltError('Duplicate Global preservation target')
    pp_nodes = {}
    for network in _children(project_node, 'Network'):
        number = _byte(_field(network, 'Address'), 'Network address')
        for unit in _children(network, 'Unit'):
            address = _byte(_field(unit, 'Address'), 'Unit address')
            path = f'//{project}/{number}/p/{address}'
            if path in allowed:
                for row in _children(unit, 'PP'):
                    if row.getAttribute('Name') in allowed[path]:
                        pp_nodes[id(row)] = True

    def shape(node):
        if node.nodeType == Node.ELEMENT_NODE:
            attributes = sorted((node.attributes.item(i).name,
                node.attributes.item(i).value) for i in range(node.attributes.length)
                if not(id(node) in pp_nodes and node.attributes.item(i).name == 'Value'))
            children = [shape(child) for child in node.childNodes
                if not(child.nodeType == Node.TEXT_NODE and not child.data.strip()
                       and any(c.nodeType == Node.ELEMENT_NODE for c in node.childNodes))]
            return ('element', node.tagName, attributes, children)
        if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE):
            return ('text', node.data)
        if node.nodeType == Node.COMMENT_NODE:
            return ('comment', node.data)
        if node.nodeType == Node.PROCESSING_INSTRUCTION_NODE:
            return ('instruction', node.target, node.data)
        raise EdltError('Unsupported native Global preservation node')

    return _json(shape(root))


@dataclass(frozen=True)
class GlobalImageContext:
    unit_path: str
    project_xml: str = field(repr=False)
    metadata: LifecycleCache
    parameter_order: tuple[str, ...]
    values: tuple[tuple[str, tuple[int, ...]], ...] = field(repr=False)
    raw_values: tuple[tuple[str, str], ...] = field(repr=False)
    source_language: int
    requirements: str = field(repr=False)
    project_images: object = field(repr=False)
    dltp_index: object = field(repr=False)
    _seal: _Seal = field(repr=False, compare=False)

    def as_dict(self):
        project = self.unit_path.split('/')[2]
        return {'format': 'cbus-edlt-global-image-context-v1',
            'profile': 'ordinary-global-source-native-project-image-provider-v1',
            'source_unit': self.unit_path, 'project_xml_sha256': _sha(self.project_xml),
            'project_graph_sha256': _sha(project_graph(self.project_xml, project)),
            'source_pp_sha256': _sha(_json(self.raw_values)),
            'source_parameter_order': list(self.parameter_order),
            'source_language': self.source_language,
            'lifecycle_metadata': self.metadata.as_dict(),
            'requirements': json.loads(self.requirements),
            'project_images': _provider(self.project_images, project=project),
            'dltp_images': _provider(self.dltp_index),
            'group_creation_performed': False, 'label_transfer_performed': False,
            'image_upload_performed': False, 'language_mutation_performed': False,
            'factory_initialization_performed': False,
            'original_execution_verified': False, 'physical_device_verified': False}


def _fingerprint(context):
    return _sha(_json(context.as_dict()))


def check_global_image_context(context, editor):
    if (type(context) is not GlobalImageContext or type(context._seal) is not _Seal):
        raise EdltError('Use an issued Global image context')
    issued = _ISSUED.get(context._seal)
    if (issued is None or issued[0] is not editor._owner
            or issued[1]() is not context or issued[2] != _fingerprint(context)
            or issued[3] is not context.project_images
            or issued[4] is not context.dltp_index):
        raise EdltError('Global image context owner, source or provider differs')
    if dict(context.values) != editor.snapshot(dict(context.raw_values)):
        raise EdltError('Global source raw PP and numeric PP differ')
    return context


def resolve_global_image_context(project_xml, unit_path, editor, *,
        project_images=None, dltp_index=None):
    if type(project_xml) is not str:
        raise EdltError('Global source project XML must be text')
    path, project, network_number, unit_number = _unit_path(unit_path)
    _provider(project_images, project=project)
    _provider(dltp_index)
    snapshot = _snapshot(project_xml, path, editor,
        project_images=project_images, dltp_index=dltp_index)
    root, project_node = _project_node(project_xml, project)
    del root
    network = _one_by_address(project_node, 'Network', network_number)
    unit = _one_by_address(network, 'Unit', unit_number)
    parameter_order = tuple(row.getAttribute('Name') for row in _children(unit, 'PP'))
    language = _default_language(network)
    requirements = editor.lifecycle.requirements(dict(snapshot.values)).as_dict()
    applications = {row.address: row for row in snapshot.applications}
    for row in requirements['applications']:
        if row['application'] not in applications:
            raise EdltError('Global source lifecycle requires an existing application '
                            + str(row['application']))
    facts = []
    for requested in requirements['groups']:
        application, number = requested['application'], requested['group']
        row = next((g for g in applications[application].groups
                    if g.address == number), None)
        if number == 255:
            # Native CBusApplication ignores stored255 and supplies its unused
            # model object; this is not a database creation or caller Boolean.
            facts.append(LifecycleGroup(application, 255, True,
                                        (False,) * 4, True, ()))
            continue
        if row is None:
            facts.append(LifecycleGroup(application, number, False))
            continue
        images = 'dynamic_images_if_present' in requested['facts']
        levels = 'complete_levels_if_present' in requested['facts']
        if images:
            native_app = _one_by_address(network, 'Application', application)
            native_group = next(g for g in _children(native_app, row.kind)
                if _byte(_field(g, 'Address'), 'Group address') == number)
            tags = _children(native_group, 'TagsDLT')
            selected = [] if not tags else [tag for tag in _children(tags[0], 'TagDLT')
                if _byte(_field(tag, 'LanguageID'), 'TagDLT language') == language]
            project_consumed = any(_field(tag, 'TagValue') and _field(tag, 'TagType') != 'ICON'
                                   for tag in selected)
            icon_consumed = any(_field(tag, 'TagType') == 'ICON' for tag in selected)
            if project_consumed and project_images is None:
                raise EdltError('Consumed Global dynamic text/font image facts require a SHA-bound ProjectImages export')
            if icon_consumed and type(dltp_index) is not DecodedDltpImages:
                raise EdltError('Consumed Global ICON facts require a SHA-bound decoded DLTP provider')
            if not row.dynamic_images_known:
                raise EdltError('Consumed Global source images are not completely known')
        if levels and any(level.value != level.address for level in row.level_records):
            raise EdltError('Global source scene Level Address/Value differs from the source alias profile')
        facts.append(LifecycleGroup(application, number, True,
            row.dynamic_images if images else None, images,
            row.levels if levels else None))
    metadata = LifecycleCache(tuple(applications), tuple(facts))
    context = GlobalImageContext(path, project_xml, metadata,
        parameter_order, snapshot.values,
        snapshot.raw_values, language, _json(requirements), project_images,
        dltp_index, _Seal())
    _ISSUED[context._seal] = (editor._owner, weakref.ref(context),
        _fingerprint(context), project_images, dltp_index)
    return check_global_image_context(context, editor)


def target_preservation_baseline(context, unit_path, before, selected_names):
    """Report each destination independently; do not load its lifecycle."""
    path, project, number, address = _unit_path(unit_path)
    if project != context.unit_path.split('/')[2]:
        raise EdltError('Global destination preservation project differs')
    _, project_node = _project_node(context.project_xml, project)
    network = _one_by_address(project_node, 'Network', number)
    unit = _one_by_address(network, 'Unit', address)
    preserved = {name: value for name, value in before.items() if name not in selected_names}
    # Raw provider bytes belong to the source only. The target baseline retains
    # its own XML facts without importing or resolving source image booleans.
    return {'path': path, 'unit_xml_sha256': _sha(unit.toxml()),
        'network_xml_sha256': _sha(network.toxml()),
        'preserved_parameter_names': list(preserved),
        'preserved_pp_sha256': _sha(_json(preserved)),
        'destination_lifecycle_loads': 0, 'label_transfer_performed': False,
        'image_upload_performed': False, 'language_mutation_performed': False}
