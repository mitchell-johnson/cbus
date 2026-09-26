"""Automatic native-project metadata for retained eDLT scene editing.

One exact ``DBGETXML`` snapshot supplies the application, group, trigger-level
and DynamicAll cache consumed by :mod:`edlt_scene_manager`.  The retained
model's trigger and action getters follow the original create-enabled
application, group and level lookups.  This module projects those exact
Trigger Control objects and creates them during one guarded native apply.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from uuid import uuid4

from .addressing import NetworkAddressing, _container
from .edlt import EdltError
from .edlt_application_cache import (
    ApplicationCache, CachedDisplay, CachedGroupList,
)
from .edlt_lifecycle import LifecycleCache, LifecycleGroup
from .edlt_parent_metadata import (
    MAX_OBJECTS, NativeEdltProjectSnapshot, _byte, _children, _digest,
    _error, _field, _json, _oid, _snapshot, _unit_path,
)
from .edlt_scene_manager import (
    EdltSceneManager, SceneDynamicLabel, SceneLevelLabels, SceneManagerCache,
)
from .native import NativeDatabase, NativeProjects, _project
from .programming import Programmer, database_address, xml_text


PROFILE = 'cbus-native-edlt-scene-metadata-v3'
PLAN_FORMAT = 'cbus-native-edlt-scene-metadata-plan-v3'
RESULT_FORMAT = 'cbus-native-edlt-scene-metadata-result-v3'
TRIGGER_APPLICATION = 202
MAX_LEVELS = 256


@dataclass(frozen=True)
class SceneLevelCreation:
    group: int
    address: int
    name: str
    reasons: tuple[str, ...]

    def as_dict(self):
        return {
            'kind': 'Level', 'application': TRIGGER_APPLICATION,
            'group': self.group, 'address': self.address,
            'value': self.address, 'name': self.name,
            'default_dynamic_labels': [
                {'value': str(variant), 'name': '', 'image_present': False}
                for variant in range(4)
            ],
            'reasons': list(self.reasons),
        }


@dataclass(frozen=True)
class SceneContainerCreation:
    kind: str
    application: int
    address: int
    name: str
    reasons: tuple[str, ...]

    def as_dict(self):
        result = {
            'kind': self.kind, 'address': self.address, 'name': self.name,
            'reasons': list(self.reasons),
        }
        if self.kind != 'Application':
            result['application'] = self.application
            result['default_dynamic_labels'] = [
                {'value': str(variant), 'name': '', 'image_present': False}
                for variant in range(4)
            ]
        return result


def _normal_operations(engine, operations):
    if not isinstance(operations, (tuple, list)) or len(operations) > 256:
        raise EdltError('Scene operations must be an array of at most 256 entries')
    return tuple(engine._operation(row) for row in operations)


def _record(snapshot, application, group):
    app = next((row for row in snapshot.applications
                if row.address == application), None)
    if app is None:
        return None
    return next((row for row in app.groups if row.address == group), None)


def _operation_facts(values, engine, snapshot, operations):
    """Replay trigger/action accesses and their original creation side effects.

    ``CBusNetwork.GetApplicationByAddress`` and
    ``CBusApplication.GetGroupByAddress`` default ``create`` to true before
    ``CBusGroup.GetLevelByAddress`` does the same.  Their event paths pass
    nonblank exact addresses to the native managers.  The projected inventory
    lets the pure retained editor observe those objects without planning I/O.
    """
    primary = engine.lifecycle._primary(values)
    secondary = values['SecondaryApplication'][0]
    scenes = []
    pairs = set()
    groups = {}
    level_groups = set()
    applications = {row.address for row in snapshot.applications}
    present_groups = {
        (row.address, group.address)
        for row in snapshot.applications for group in row.groups
    }
    levels = {
        (row.address, group.address): set(group.levels)
        for row in snapshot.applications for group in row.groups
    }
    application_reasons = []
    group_creation_reasons = {}
    creation_reasons = {}

    def group(application, address, reason, *, levels=False):
        groups.setdefault((application, address), []).append(reason)
        if levels:
            level_groups.add((application, address))

    def ensure_trigger_application(reason):
        if TRIGGER_APPLICATION not in applications:
            application_reasons.append(reason)
            applications.add(TRIGGER_APPLICATION)

    def retain_trigger(trigger, reason):
        """Match TriggerGroup.get without invoking ActionSelector.get."""
        ensure_trigger_application(reason)
        if trigger == 255:
            return 255
        key = (TRIGGER_APPLICATION, trigger)
        if key not in present_groups:
            group_creation_reasons.setdefault(trigger, []).append(reason)
            present_groups.add(key)
            levels[key] = set()
        group(TRIGGER_APPLICATION, trigger, reason)
        return trigger

    def ensure_level(trigger, address, reason):
        if address < 0:
            return False
        key = (TRIGGER_APPLICATION, trigger)
        present = levels[key]
        if address not in present:
            if len(present) >= MAX_LEVELS:
                raise ValueError(
                    f'Trigger group {trigger} has no level capacity')
            creation_reasons.setdefault((trigger, address), []).append(reason)
            present.add(address)
        pairs.add((trigger, address))
        return True

    def get_action(trigger, raw_action, reason):
        """Return updated raw state and the ActionSelector getter result."""
        trigger = retain_trigger(trigger, reason)
        if trigger == 255:
            # The retained getter reports -1 but leaves its raw field intact.
            return trigger, raw_action, -1
        group(TRIGGER_APPLICATION, trigger, reason, levels=True)
        if not ensure_level(trigger, raw_action, reason):
            return trigger, -1, -1
        return trigger, raw_action, raw_action

    def set_action(trigger, raw_action, requested, reason):
        """Match ActionSelector.set, including absent-trigger preservation."""
        trigger = retain_trigger(trigger, reason)
        if trigger == 255:
            return trigger, raw_action
        group(TRIGGER_APPLICATION, trigger, reason, levels=True)
        if not ensure_level(trigger, requested, reason):
            return trigger, -1
        return trigger, requested

    for slot, _pointer, header, _items in engine.lifecycle._scenes(values):
        variant = 1 if header[0] & 1 and secondary != 255 else 0
        trigger, action, _returned = get_action(
            header[2], header[3], f'Scene{slot} initial trigger/action')
        if trigger == 255:
            # Lifecycle load, unlike later ActionSelector access, normalizes
            # an absent trigger's stored action to -1.
            action = -1
        scenes.append([variant, trigger, action])

    clipboard = None
    for number, operation in enumerate(operations, 1):
        slot = operation['scene'] - 1
        kind = operation['op']
        scene = scenes[slot]
        reason = f'operation {number} {kind}'
        if kind == 'set-application':
            scene[0] = operation['selector']
        elif kind == 'add-groups':
            application = secondary if scene[0] else primary
            if application == 255:
                raise EdltError('Secondary scene application is disabled')
            for address in operation['groups']:
                group(application, address, reason)
        elif kind == 'set-trigger':
            scene[1] = operation['group']
        elif kind == 'set-action':
            scene[1], scene[2] = set_action(
                scene[1], scene[2], operation['action'], reason)
        elif kind == 'get-trigger':
            scene[1] = retain_trigger(scene[1], reason)
        elif kind == 'get-action':
            scene[1], scene[2], _returned = get_action(
                scene[1], scene[2], reason)
        elif kind == 'copy':
            scene[1], scene[2], returned = get_action(
                scene[1], scene[2], reason)
            clipboard = (scene[0], scene[1], returned)
        elif kind == 'paste' and clipboard is not None:
            source = list(clipboard)
            source[1], source[2], returned = get_action(
                source[1], source[2], reason)
            scenes[slot] = [source[0], source[1], returned]
            scene = scenes[slot]
        elif kind == 'clear-scene':
            scenes[slot] = [0, 255, -1]

    for slot, scene in enumerate(scenes, 1):
        scene[1], scene[2], returned = get_action(
            scene[1], scene[2], f'Scene{slot} terminal trigger/action')
        if returned < 0:
            scene[1], scene[2] = set_action(
                scene[1], scene[2], 0,
                f'Scene{slot} save fallback action')
            scene[1], scene[2], _returned = get_action(
                scene[1], scene[2],
                f'Scene{slot} terminal fallback action')
    containers = []
    if application_reasons:
        containers.append(SceneContainerCreation(
            'Application', TRIGGER_APPLICATION, TRIGGER_APPLICATION,
            'Trigger Control', tuple(dict.fromkeys(application_reasons))))
    containers.extend(
        SceneContainerCreation(
            'Group', TRIGGER_APPLICATION, trigger, f'Group {trigger}',
            tuple(dict.fromkeys(group_creation_reasons[trigger])))
        for trigger in sorted(group_creation_reasons)
    )
    level_creations = tuple(
        SceneLevelCreation(
            trigger, address, f'Action Selector {address}',
            tuple(dict.fromkeys(creation_reasons[(trigger, address)])))
        for trigger, address in sorted(creation_reasons)
    )
    projected = {
        key: tuple(sorted(value)) for key, value in levels.items()
    }
    return (groups, level_groups, tuple(sorted(pairs)),
            tuple(containers) + level_creations, projected,
            frozenset(applications), frozenset(present_groups))


@dataclass(frozen=True)
class ResolvedSceneMetadata:
    snapshot: NativeEdltProjectSnapshot
    operations: tuple
    cache: SceneManagerCache
    requirements: str
    action_pairs: tuple[tuple[int, int], ...]
    creations: tuple[SceneContainerCreation | SceneLevelCreation, ...]
    group_reasons: str

    def as_dict(self):
        return {
            'format': 'cbus-native-edlt-scene-cache-v3',
            'profile': PROFILE,
            'cache': self.cache.as_dict(),
            'requirements': json.loads(self.requirements),
            'consumed_trigger_actions': [
                {'group': group, 'action': action}
                for group, action in self.action_pairs
            ],
            'planned_creations': [row.as_dict() for row in self.creations],
            'planned_level_creations': [
                row.as_dict() for row in self.creations
                if isinstance(row, SceneLevelCreation)
            ],
            'group_reasons': json.loads(self.group_reasons),
            'metadata_provenance': 'one-admitted-native-project-xml-snapshot',
            'metadata_objects_created': False,
            'missing_objects_auto_created': False,
            'missing_objects_projected_for_creation': bool(self.creations),
            'projected_cache_includes_planned_creations': True,
            'project_images_loaded': False,
            'unresolved_image_metadata_rejected_when_consumed': True,
        }


def resolve_native_scene_metadata(text, unit_path, values, engine, operations):
    """Resolve one immutable SceneManager cache without native mutation."""
    if type(engine) is not EdltSceneManager:
        raise ValueError('Expected an EdltSceneManager engine')
    operations = _normal_operations(engine, operations)
    unit_path, _project_name, _network, _unit = _unit_path(unit_path)
    snapshot = _snapshot(text, unit_path, engine)
    supplied = engine.snapshot(values)
    if supplied != snapshot.value_map():
        raise ValueError('PP snapshot differs from the selected native project unit')

    requirements = engine.lifecycle.requirements(supplied).as_dict()
    applications = {row.address: row for row in snapshot.applications}
    required_apps = {row['application'] for row in requirements['applications']}
    missing_apps = sorted(required_apps - set(applications)
                          - {TRIGGER_APPLICATION})
    if missing_apps:
        raise ValueError('Required native applications are absent: '
                         + ', '.join(map(str, missing_apps)))

    group_reasons = {}
    level_groups = set()
    requirements_by_group = {}
    for row in requirements['groups']:
        key = (row['application'], row['group'])
        requirements_by_group[key] = row
        group_reasons.setdefault(key, []).extend(row['facts']['exists'])
        if row['facts'].get('complete_levels_if_present'):
            level_groups.add(key)
    (extra_groups, extra_levels, action_pairs, creations, projected_levels,
     projected_applications, projected_groups) = _operation_facts(
        supplied, engine, snapshot, operations)
    object_count = 1 + sum(
        1 + sum(1 + len(group.level_records) for group in application.groups)
        for application in snapshot.applications)
    if object_count + len(creations) > MAX_OBJECTS:
        raise ValueError(
            'Native eDLT metadata creation would exceed 4096 objects')
    for key, reasons in extra_groups.items():
        group_reasons.setdefault(key, []).extend(reasons)
    level_groups.update(extra_levels)

    cache_groups = []
    for (application, group), reasons in sorted(group_reasons.items()):
        if application not in projected_applications:
            raise ValueError('Required native application is absent: '
                             + str(application))
        if group == 255:
            cache_groups.append(LifecycleGroup(
                application, 255, True, (False,) * 4, True, ()))
            continue
        record = _record(snapshot, application, group)
        if record is None:
            if (application, group) not in projected_groups:
                cache_groups.append(LifecycleGroup(application, group, False))
                continue
            cached_levels = (projected_levels[(application, group)]
                             if (application, group) in level_groups else None)
            cache_groups.append(LifecycleGroup(
                application, group, True, (False,) * 4, True,
                cached_levels))
            continue
        facts = requirements_by_group.get((application, group), {}).get(
            'facts', {})
        needs_images = bool(facts.get('dynamic_images_if_present'))
        if needs_images and not record.dynamic_images_known:
            raise ValueError(
                'Consumed dynamic image metadata is not derivable from DBGETXML; '
                f'application {application} group {group} requires project/DLTP images')
        cached_levels = (projected_levels[(application, group)]
                         if (application, group) in level_groups else None)
        cache_groups.append(LifecycleGroup(
            application, group, True,
            record.dynamic_images if needs_images else None,
            needs_images,
            cached_levels))
    if len(cache_groups) > 512:
        raise ValueError('Resolved eDLT scene cache exceeds 512 group facts')

    lifecycle = LifecycleCache(
        tuple(sorted(projected_applications)), tuple(cache_groups))
    container_creations = {
        (row.kind, row.application, row.address): row
        for row in creations if isinstance(row, SceneContainerCreation)
    }
    displays = tuple(
        CachedDisplay(address,
                      (applications[address].tag
                       if address in applications
                       else container_creations[
                           ('Application', address, address)].name),
                      (applications[address].tag
                       if address in applications
                       else container_creations[
                           ('Application', address, address)].name))
        for address in sorted(projected_applications))
    virtual_apps = {row.application for row in cache_groups
                    if row.group == 255 and row.exists}
    group_lists = []
    for address in sorted(projected_applications):
        existing = applications.get(address)
        rows = ({row.address: CachedDisplay(row.address, row.tag, row.tag)
                 for row in existing.groups} if existing is not None else {})
        for (kind, application, group), creation in container_creations.items():
            if kind == 'Group' and application == address:
                rows[group] = CachedDisplay(group, creation.name, creation.name)
        if address in virtual_apps:
            rows[255] = CachedDisplay(255, '<Unused>', '<Unused>')
        group_lists.append(CachedGroupList(
            address, True, tuple(rows[key] for key in sorted(rows))))
    application_cache = ApplicationCache(
        lifecycle, True, displays, tuple(group_lists))

    level_labels = []
    for group_address, action in action_pairs:
        group = _record(snapshot, 202, group_address)
        level = None if group is None else next(
            (row for row in group.level_records if row.address == action), None)
        creation = next((row for row in creations
                         if isinstance(row, SceneLevelCreation)
                         if (row.group, row.address)
                         == (group_address, action)), None)
        if level is None and creation is None:
            raise ValueError(
                f'Resolved trigger action disappeared: {group_address}/{action}')
        if level is not None and not level.dynamic_labels_known:
            raise ValueError(
                'Consumed trigger action image metadata is not derivable from '
                f'DBGETXML: group {group_address} action {action}')
        level_labels.append(SceneLevelLabels(
            group_address, action,
            tuple(SceneDynamicLabel(*row) for row in (
                level.dynamic_labels if level is not None
                else tuple((str(variant), '', False)
                           for variant in range(4))))))
    cache = SceneManagerCache(application_cache, tuple(level_labels))
    reasons = _json([
        {'application': application, 'group': group,
         'reasons': list(dict.fromkeys(group_reasons[(application, group)]))}
        for application, group in sorted(group_reasons)
    ])
    return ResolvedSceneMetadata(
        snapshot, operations, cache, _json(requirements), action_pairs,
        creations, reasons)


@dataclass(frozen=True)
class NativeSceneMetadataPlan:
    unit: str
    before_xml: str
    resolved: ResolvedSceneMetadata
    networks: tuple[str, ...]
    validate: bool
    scene_plan: object

    def semantic_source(self):
        return (
            self.resolved.snapshot, self.resolved.operations,
            self.resolved.cache, self.resolved.creations, self.validate,
            tuple(sorted(self.scene_plan.expected.items())),
            tuple(sorted(self.scene_plan.changes.items())),
        )

    def as_dict(self):
        snapshot = self.resolved.snapshot
        return {
            'format': PLAN_FORMAT,
            'profile': PROFILE,
            'unit': self.unit,
            'project_xml_sha256': _digest(self.before_xml),
            'parameters_sha256': _digest(_json({
                name: list(value) for name, value in snapshot.values
            })),
            'automatic_metadata': self.resolved.as_dict(),
            'scene_manager': self.scene_plan.as_dict(),
            'validation_requested': self.validate,
            'closed_networks': list(self.networks),
            'caller_exclusive_project_required': True,
            'database_only': True,
            'metadata_mutation_planned': bool(self.resolved.creations),
            'planned_creations': [
                row.as_dict() for row in self.resolved.creations
            ],
            'creation_order': ('Trigger Control application, trigger groups by '
                               'address, then exact requested action addresses'),
            'native_missing_application_name': 'Trigger Control',
            'native_missing_group_name': 'Group {address}',
            'native_missing_level_name': 'Action Selector {address}',
            'original_group_auto_add_admission': (
                'fresh CBusNetwork defaults: AutoAddGroupsMessageShown=false, '
                'bAdd=true; no prior interactive decline'),
            'native_blank_add_dialog_allocation': (
                'separate interactive path: first free address 0..254, seed '
                'Level {address}, create only after acceptance'),
            'mutation_required': bool(
                self.resolved.creations or self.scene_plan.changes),
            'stale_project_and_pp_rechecked_before_apply': True,
            'connected_staging_rollback': True,
            'backup_required_for_metadata_creation': bool(
                self.resolved.creations),
            'batch_atomic': False,
            'atomic_boundary': (
                'DBADDSAFE/DBSETSAFE, PP SAVE and PROJECT SAVE are separate'),
            'rollback_before_first_persistence_save': True,
            'rollback_before_pp_save': True,
            'rollback_after_pp_save_attempt': False,
            'rollback_after_target_project_save_attempt': False,
            'automatic_retries': 0,
            'full_scene_manager_control_binding_verified': False,
            'physical_device_programmed': False,
        }


def plan_native_scene_metadata(text, unit_path, values, editor, operations,
                               *, validate=False, networks=()):
    """Resolve project metadata and prepare one retained scene plan offline."""
    from .edlt_scene_manager_cli import SceneCLIEditor
    if type(editor) is not SceneCLIEditor:
        raise ValueError('Expected a SceneCLIEditor')
    unit_path, _project_name, _network, _unit = _unit_path(unit_path)
    resolved = resolve_native_scene_metadata(
        text, unit_path, values, editor.engine, operations)
    scene_plan = editor.plan(
        resolved.snapshot.value_map(), metadata=resolved.cache,
        operations=resolved.operations, validate=validate)
    return NativeSceneMetadataPlan(
        unit_path, text, resolved, tuple(networks), bool(validate), scene_plan)


@dataclass(frozen=True)
class NativeSceneMetadataResult:
    document: str

    def as_dict(self):
        return json.loads(self.document)


class NativeSceneMetadataError(RuntimeError):
    def __init__(self, cause, result):
        self.cause, self.result = cause, result
        self.details = {'edlt_scene_metadata_evidence': result.as_dict()}
        super().__init__('Native eDLT scene transaction stopped: '
                         + _error(cause)['message'])


class NativeSceneMetadataTransaction:
    """Single-use exact metadata plus retained SceneManager transaction."""
    def __init__(self, client, editor, *, programmer=None):
        from .edlt_scene_manager_cli import SceneCLIEditor
        if type(editor) is not SceneCLIEditor:
            raise ValueError('Expected a SceneCLIEditor')
        self.client, self.editor = client, editor
        self.database = NativeDatabase(client)
        self.projects = NativeProjects(client)
        self.programmer = Programmer(client) if programmer is None else programmer
        self.network_guard = NetworkAddressing(client)
        self._plans, self._fingerprints, self._consumed = [], {}, set()
        self.last_result = None
        self._evidence = None

    def _start(self, operation):
        self.last_result = None
        self._evidence = {
            'format': RESULT_FORMAT, 'profile': PROFILE,
            'operation': operation, 'state': 'preconditions',
            'complete': False, 'saved': False, 'commands': [], 'objects': [],
            'backup_created': False,
            'backup_source_save_attempted': False,
            'backup_source_save_confirmed': False,
            'backup_source_save_outcome_uncertain': False,
            'backup_copy_attempted': False,
            'backup_copy_confirmed': False,
            'backup_copy_outcome_uncertain': False,
            'metadata_mutation_attempted': False,
            'metadata_objects_created': 0,
            'pp_mutation_attempted': False,
            'pp_readback_verified': False,
            'pp_save_attempted': False, 'pp_save_confirmed': False,
            'pp_save_outcome_uncertain': False,
            'target_project_save_attempted': False,
            'target_project_save_confirmed': False,
            'target_project_save_outcome_uncertain': False,
            'persistence_verified': False,
            'rollback_attempted': False, 'rollback_verified': False,
            'rollback_errors': [], 'pp_state_uncertain': False,
            'database_state_uncertain': False,
            'partial_failure_possible': False,
            'unidentified_metadata_mutation': False,
            'database_persistence': 'not-attempted',
            'batch_atomic': False,
            'automatic_retries': 0,
            'caller_exclusive_project_required': True,
            'server_project_edit_lock_acquired': False,
            'full_scene_manager_control_binding_verified': False,
            'physical_device_programmed': False,
        }

    def _finish(self):
        self.last_result = NativeSceneMetadataResult(_json(self._evidence))
        return self.last_result

    def _fail(self, error):
        backup_save_uncertain = (
            self._evidence['backup_source_save_attempted']
            and not self._evidence['backup_source_save_confirmed'])
        backup_copy_uncertain = (
            self._evidence['backup_copy_attempted']
            and not self._evidence['backup_copy_confirmed'])
        pp_save_uncertain = (self._evidence['pp_save_attempted']
                             and not self._evidence['pp_save_confirmed'])
        project_save_uncertain = (
            self._evidence['target_project_save_attempted']
            and not self._evidence['target_project_save_confirmed'])
        staging = self._evidence.get('staging_evidence') or {}
        rollback_verified = (self._evidence['rollback_verified']
                             or bool(staging.get('rollback_verified')))
        rollback_attempted = (self._evidence['rollback_attempted']
                              or bool(staging.get('attempted_parameters')))
        rollback_errors = [*self._evidence['rollback_errors'],
                           *staging.get('rollback_errors', ())]
        crossed_save_boundary = (self._evidence['pp_save_attempted']
                                 or self._evidence[
                                     'target_project_save_attempted'])
        rollback_uncertain = rollback_attempted and not rollback_verified
        uncertain = (backup_save_uncertain or backup_copy_uncertain
                     or pp_save_uncertain or project_save_uncertain
                     or rollback_uncertain
                     or (crossed_save_boundary and not rollback_verified
                         and not self._evidence['persistence_verified']))
        if rollback_verified:
            persistence = 'original-state-verified-after-rollback'
        elif (self._evidence['target_project_save_confirmed']
              and not self._evidence['persistence_verified']):
            persistence = 'save-confirmed-verification-incomplete'
        elif uncertain:
            persistence = 'uncertain'
        elif self._evidence['pp_save_confirmed']:
            persistence = 'pp-save-confirmed-project-persistence-incomplete'
        else:
            persistence = 'not-saved'
        self._evidence.update(
            complete=False, saved=False, error=_error(error),
            state='uncertain' if uncertain else 'stopped',
            rollback_attempted=rollback_attempted,
            rollback_verified=rollback_verified,
            rollback_errors=rollback_errors,
            backup_source_save_outcome_uncertain=backup_save_uncertain,
            backup_copy_outcome_uncertain=backup_copy_uncertain,
            pp_save_outcome_uncertain=pp_save_uncertain,
            target_project_save_outcome_uncertain=project_save_uncertain,
            pp_state_uncertain=(pp_save_uncertain or rollback_uncertain),
            database_state_uncertain=uncertain,
            partial_failure_possible=(
                self._evidence['backup_created']
                or crossed_save_boundary or uncertain),
            database_persistence=persistence,
        )
        result = self._finish()
        if not isinstance(error, Exception):
            try:
                error.edlt_scene_metadata_evidence = result.as_dict()
            except BaseException:
                pass
            raise error
        raise NativeSceneMetadataError(error, result) from error

    def _xml(self, project):
        response = self.database.get('//' + project, xml=True)
        if response.code != 344:
            raise RuntimeError('Native project XML response did not complete')
        return xml_text(response)

    def _operation(self, action, project, other=None):
        row = {'command': 'PROJECT ' + action.upper(), 'attempted': True,
               'completed': False}
        self._evidence['commands'].append(row)
        result = self.projects.operation(action, project, other)
        row.update(completed=True, code=result.code)
        if result.code != 200 or len(result.lines) != 1:
            raise RuntimeError(
                'Native project operation did not return one completion')
        return result

    def _closed_networks(self, project, text):
        root = _container(text, 'Installation').documentElement
        projects = _children(root, 'Project')
        if len(projects) != 1 or _field(projects[0], 'Address') != project:
            raise ValueError('Expected exactly the selected native project')
        paths = ['//' + project + '/' + str(_byte(
            _field(node, 'Address'), 'Network address'))
                 for node in _children(projects[0], 'Network')]
        if not paths or len(paths) != len(set(paths)):
            raise ValueError('Project must contain unique networks')
        for path in paths:
            runtime = dict(self.network_guard._runtime(path))
            if any(runtime.get(name) != value for name, value in (
                    ('InterfaceState', 'closed'),
                    ('TargetInterfaceState', 'closed'),
                    ('SyncState', 'idle'))):
                raise ValueError(
                    'Every project network must be closed with synchronization idle')
        return tuple(sorted(paths))

    def plan(self, unit, *, operations, validate=False,
             exclusive_project=False):
        self._start('plan')
        try:
            if exclusive_project is not True:
                raise ValueError(
                    'Caller must exclusively own project editing/reloading')
            if len(self._plans) >= 16:
                raise ValueError('Use a new manager after sixteen issued plans')
            unit, project, _network, _address = _unit_path(unit)
            text = self._xml(project)
            networks = self._closed_networks(project, text)
            values = _snapshot(text, unit, self.editor.engine).value_map()
            plan = plan_native_scene_metadata(
                text, unit, values, self.editor, operations,
                validate=validate, networks=networks)
            self._plans.append(plan)
            self._fingerprints[id(plan)] = repr(plan)
            self._evidence.update(
                state='planned', complete=True, plan=plan.as_dict())
            self._finish()
            return plan
        except BaseException as error:
            self._fail(error)

    def _issued(self, plan):
        if (type(plan) is not NativeSceneMetadataPlan
                or not any(plan is row for row in self._plans)
                or self._fingerprints.get(id(plan)) != repr(plan)):
            raise ValueError(
                'Use an unchanged native eDLT scene plan issued by this manager')

    def _fresh(self, plan, *, exact=False):
        snapshot = plan.resolved.snapshot
        text = self._xml(snapshot.project)
        if self._closed_networks(snapshot.project, text) != plan.networks:
            raise ValueError('Project network inventory changed since planning')
        current = plan_native_scene_metadata(
            text, plan.unit, snapshot.value_map(), self.editor,
            plan.resolved.operations, validate=plan.validate,
            networks=plan.networks)
        if exact and text != plan.before_xml:
            raise ValueError('Native project XML changed since planning')
        if current.semantic_source() != plan.semantic_source():
            raise ValueError('Native eDLT scene metadata or PP state changed since planning')
        return text

    @staticmethod
    def _metadata_equal(before, after):
        return (
            before.unit_oid == after.unit_oid
            and before.project_metadata == after.project_metadata
            and before.unit_metadata == after.unit_metadata
            and before.network_metadata == after.network_metadata
            and before.other_networks == after.other_networks
            and before.other_units == after.other_units
            and before.applications == after.applications
        )

    def _add(self, plan, creation, known):
        root = (f'//{plan.resolved.snapshot.project}/'
                f'{plan.resolved.snapshot.network}')
        if isinstance(creation, SceneContainerCreation):
            if creation.kind == 'Application':
                parent, kind = root, 'application'
            else:
                parent, kind = root + f'/{creation.application}', 'group'
        else:
            parent = root + f'/{TRIGGER_APPLICATION}/{creation.group}'
            kind = 'level'
        receipt = {**creation.as_dict(), 'attempted': True, 'created': False,
                   'value_initialized': False}
        try:
            response = self.database.add(
                parent, kind, creation.address,
                creation.name)
        except BaseException:
            self._evidence['unidentified_metadata_mutation'] = True
            raise
        identities = [match[1].lower() for line in response.lines
                      if (match := re.fullmatch(
                          r'301[- ]OID=([0-9a-fA-F-]{36})', line))]
        if len(identities) != 1:
            self._evidence['unidentified_metadata_mutation'] = True
            raise RuntimeError(
                'Created scene metadata did not return exactly one OID')
        try:
            identity = _oid(identities[0])
        except ValueError:
            self._evidence['unidentified_metadata_mutation'] = True
            raise
        if identity in known:
            self._evidence['unidentified_metadata_mutation'] = True
            raise RuntimeError('Created scene metadata returned an existing OID')
        known.add(identity)
        receipt.update(
            oid=identity, created=True,
            value_initialized=isinstance(creation, SceneLevelCreation))
        self._evidence['objects'].append(receipt)
        self._evidence['metadata_objects_created'] = len(
            self._evidence['objects'])

    def _verify_created(self, plan, text):
        snapshot = _snapshot(text, plan.unit, self.editor.engine)
        before_apps = {row.address: row
                       for row in plan.resolved.snapshot.applications}
        after_apps = {row.address: row for row in snapshot.applications}
        app_creations = {
            row.address: row for row in plan.resolved.creations
            if (isinstance(row, SceneContainerCreation)
                and row.kind == 'Application')
        }
        group_creations = {
            (row.application, row.address): row
            for row in plan.resolved.creations
            if (isinstance(row, SceneContainerCreation)
                and row.kind == 'Group')
        }
        level_creations = {
            (TRIGGER_APPLICATION, row.group, row.address): row
            for row in plan.resolved.creations
            if isinstance(row, SceneLevelCreation)
        }
        if set(after_apps) != set(before_apps) | set(app_creations):
            raise RuntimeError(
                'Native application inventory changed during the transaction')
        receipts = {}
        for row in self._evidence['objects']:
            if row['kind'] == 'Application':
                key = ('Application', row['address'], None, row['address'])
            else:
                key = (row['kind'], row['application'], row.get('group'),
                       row['address'])
            if key in receipts:
                raise RuntimeError('Duplicate scene metadata creation receipt')
            receipts[key] = row

        for app_address, after_app in after_apps.items():
            before_app = before_apps.get(app_address)
            if before_app is None:
                creation = app_creations.get(app_address)
                receipt = receipts.get(
                    ('Application', app_address, None, app_address))
                if (creation is None or receipt is None
                        or after_app.oid != receipt['oid']
                        or after_app.tag != creation.name):
                    raise RuntimeError(
                        'Created scene application differs after native readback')
            elif (after_app.oid, after_app.tag, after_app.metadata) != (
                    before_app.oid, before_app.tag, before_app.metadata):
                raise RuntimeError('Existing application metadata changed')

            before_groups = ({row.address: row for row in before_app.groups}
                             if before_app is not None else {})
            expected_group_creations = {
                address: row for (application, address), row
                in group_creations.items() if application == app_address
            }
            after_groups = {row.address: row for row in after_app.groups}
            if set(after_groups) != (set(before_groups)
                                     | set(expected_group_creations)):
                raise RuntimeError(
                    'Native group inventory changed during the transaction')

            for group_address, after_group in after_groups.items():
                before_group = before_groups.get(group_address)
                if before_group is None:
                    creation = expected_group_creations.get(group_address)
                    receipt = receipts.get(
                        ('Group', app_address, None, group_address))
                    if (creation is None or receipt is None
                            or after_group.kind != 'Group'
                            or after_group.oid != receipt['oid']
                            or after_group.tag != creation.name
                            or not after_group.dynamic_images_known
                            or after_group.dynamic_images != (False,) * 4):
                        raise RuntimeError(
                            'Created scene group differs after native readback')
                elif (after_group.kind, after_group.oid, after_group.tag,
                      after_group.metadata, after_group.dynamic_images,
                      after_group.dynamic_images_known) != (
                          before_group.kind, before_group.oid,
                          before_group.tag, before_group.metadata,
                          before_group.dynamic_images,
                          before_group.dynamic_images_known):
                    raise RuntimeError('Existing group metadata changed')

                before_levels = (
                    {row.address: row for row in before_group.level_records}
                    if before_group is not None else {})
                expected_new = {
                    address: creation
                    for (application, group, address), creation
                    in level_creations.items()
                    if (application, group) == (app_address, group_address)
                }
                after_levels = {row.address: row
                                for row in after_group.level_records}
                if set(after_levels) != set(before_levels) | set(expected_new):
                    raise RuntimeError(
                        'Native level inventory changed during the transaction')
                for address, row in before_levels.items():
                    if after_levels[address] != row:
                        raise RuntimeError('Existing level metadata changed')
                for address, creation in expected_new.items():
                    row = after_levels[address]
                    receipt = receipts.get(
                        ('Level', app_address, group_address, address))
                    blanks = tuple((str(variant), '', False)
                                   for variant in range(4))
                    if (receipt is None or row.oid != receipt['oid']
                            or row.address != address or row.value != address
                            or row.tag != creation.name
                            or not row.dynamic_labels_known
                            or row.dynamic_labels != blanks):
                        raise RuntimeError(
                            'Created scene level differs after native readback')

        expected_receipts = len(plan.resolved.creations)
        if len(receipts) != expected_receipts:
            raise RuntimeError('Scene metadata creation receipts are incomplete')
        before = plan.resolved.snapshot
        if (snapshot.unit_oid != before.unit_oid
                or snapshot.project_metadata != before.project_metadata
                or snapshot.unit_metadata != before.unit_metadata
                or snapshot.network_metadata != before.network_metadata
                or snapshot.other_networks != before.other_networks
                or snapshot.other_units != before.other_units):
            raise RuntimeError(
                'Unrelated native project/unit/network metadata changed')
        return snapshot

    def _rollback_pre_save(self, plan):
        self._evidence['rollback_attempted'] = True
        try:
            if not self._evidence['unidentified_metadata_mutation']:
                for row in reversed(self._evidence['objects']):
                    row['rollback_delete_attempted'] = True
                    self.database.delete('!' + row['oid'])
                    row['rollback_delete_confirmed'] = True
                self._operation('save', plan.resolved.snapshot.project)
                self._evidence['rollback_project_save_confirmed'] = True
            # When an add reply is ambiguous, do not persist an unidentified
            # object.  Reload the source snapshot saved immediately before the
            # backup and establish the actual result from DBGETXML.
            for action in ('close', 'load'):
                self._operation(action, plan.resolved.snapshot.project)
            text = self._xml(plan.resolved.snapshot.project)
            current = _snapshot(text, plan.unit, self.editor.engine)
            if current != plan.resolved.snapshot:
                raise RuntimeError(
                    'Reload did not restore the admitted scene metadata source')
            self._evidence['rollback_verified'] = True
        except BaseException as error:
            self._evidence['rollback_errors'].append(_error(error))

    def apply(self, plan, *, backup_project=None):
        self._start('apply')
        pp_save_attempted = False
        try:
            self._issued(plan)
            if id(plan) in self._consumed:
                raise ValueError('This plan already had an apply attempt')
            self._consumed.add(id(plan))
            backup = None
            if plan.resolved.creations:
                backup = (_project(backup_project)
                          if backup_project is not None
                          else 'B' + uuid4().hex[:7].upper())
                if backup.upper() == plan.resolved.snapshot.project.upper():
                    raise ValueError(
                        'Backup project must differ from the edited project')
            elif backup_project is not None:
                raise ValueError(
                    '--backup-project requires a planned metadata creation')
            self._evidence['plan'] = plan.as_dict()
            if backup is not None:
                self._evidence['backup_project'] = backup
            self._fresh(plan, exact=True)
            snapshot = plan.resolved.snapshot
            if not plan.resolved.creations and not plan.scene_plan.changes:
                self._evidence.update(
                    state='verified_noop', complete=True, saved=False,
                    database_persistence='unchanged-source-verified',
                    persistence_verified=True,
                    existing_metadata_preserved=True,
                    unrelated_unit_and_network_metadata_preserved=True)
                return self._finish()

            if plan.resolved.creations:
                self._evidence['state'] = 'backup'
                self._evidence['backup_source_save_attempted'] = True
                self._operation('save', snapshot.project)
                self._evidence['backup_source_save_confirmed'] = True
                self._evidence['backup_copy_attempted'] = True
                self._operation('copy', snapshot.project, backup)
                self._evidence['backup_copy_confirmed'] = True
                self._evidence['backup_created'] = True
                self._fresh(plan)
                self._operation('use', snapshot.project)
                self._evidence.update(
                    state='metadata', metadata_mutation_attempted=True)
                known = {snapshot.unit_oid}
                for application in snapshot.applications:
                    known.add(application.oid)
                    for group in application.groups:
                        known.add(group.oid)
                        known.update(level.oid
                                     for level in group.level_records)
                for creation in plan.resolved.creations:
                    self._add(plan, creation, known)
                created = self._verify_created(
                    plan, self._xml(snapshot.project))
                if created.value_map() != snapshot.value_map():
                    raise ValueError(
                        'PP source changed during native scene level creation')

            if plan.scene_plan.changes:
                lock = f'//{snapshot.project}/{snapshot.network}'
                self._evidence.update(state='pp', pp_mutation_attempted=True)
                with self.programmer.load(
                        lock, database_address(plan.unit)) as session:
                    if self.editor.snapshot(
                            session.values()) != snapshot.value_map():
                        raise ValueError(
                            'PP source changed after automatic scene metadata planning')
                    try:
                        staged = self.editor.engine.apply(
                            session, plan.scene_plan)
                    except BaseException:
                        if isinstance(self.editor.last_evidence, dict):
                            self._evidence['staging_evidence'] = (
                                self.editor.last_evidence)
                        raise
                    self._evidence['staging_evidence'] = staged
                    self._evidence['pp_readback_verified'] = bool(
                        staged.get('verified'))
                    self._evidence.update(
                        state='pp_save', pp_save_attempted=True)
                    pp_save_attempted = True
                    session.save_to_source()
                    self._evidence['pp_save_confirmed'] = True

            if plan.resolved.creations:
                self._evidence.update(
                    state='project_save',
                    target_project_save_attempted=True)
                self._operation('save', snapshot.project)
                self._evidence['target_project_save_confirmed'] = True
                for action in ('close', 'load'):
                    self._operation(action, snapshot.project)

            self._evidence['state'] = 'verify'
            final_text = self._xml(snapshot.project)
            final = (self._verify_created(plan, final_text)
                     if plan.resolved.creations else
                     _snapshot(final_text, plan.unit, self.editor.engine))
            expected = {**plan.scene_plan.expected, **plan.scene_plan.changes}
            if final.value_map() != expected:
                raise RuntimeError(
                    'Persisted native PP differs from the scene transaction')
            if (not plan.resolved.creations
                    and not self._metadata_equal(snapshot, final)):
                raise RuntimeError(
                    'Native project metadata changed during the scene transaction')
            self._evidence.update(
                state='verified_saved', complete=True, saved=True,
                database_persistence=(
                    'verified-after-project-reload'
                    if plan.resolved.creations
                    else 'verified-after-dbgetxml'),
                persistence_verified=True,
                existing_metadata_preserved=True,
                unrelated_unit_and_network_metadata_preserved=True,
                parameters_sha256=_digest(_json({
                    name: list(value) for name, value in final.values
                })),
            )
            return self._finish()
        except BaseException as error:
            if (not pp_save_attempted
                    and not self._evidence.get('target_project_save_attempted')
                    and self._evidence.get('backup_created')
                    and self._evidence.get('metadata_mutation_attempted')):
                self._rollback_pre_save(plan)
            self._fail(error)
