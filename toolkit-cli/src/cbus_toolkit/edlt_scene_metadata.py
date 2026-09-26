"""Automatic native-project metadata for retained eDLT scene editing.

The resolver is intentionally read-only with respect to database metadata.  It
turns one exact ``DBGETXML`` snapshot into the complete application, group,
trigger-level and DynamicAll cache consumed by :mod:`edlt_scene_manager`.
Missing objects remain explicit absence facts; this module does not invent the
original add-dialog naming policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from .addressing import NetworkAddressing, _container
from .edlt import EdltError
from .edlt_application_cache import (
    ApplicationCache, CachedDisplay, CachedGroupList,
)
from .edlt_lifecycle import LifecycleCache, LifecycleGroup
from .edlt_parent_metadata import (
    NativeEdltProjectSnapshot, _byte, _children, _digest, _error, _field,
    _json, _snapshot, _unit_path,
)
from .edlt_scene_manager import (
    EdltSceneManager, SceneDynamicLabel, SceneLevelLabels, SceneManagerCache,
)
from .native import NativeDatabase
from .programming import Programmer, database_address, xml_text


PROFILE = 'cbus-native-edlt-scene-metadata-v1'
PLAN_FORMAT = 'cbus-native-edlt-scene-metadata-plan-v1'
RESULT_FORMAT = 'cbus-native-edlt-scene-metadata-result-v1'


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
    """Return extra group facts and every valid action label consumed in order."""
    primary = engine.lifecycle._primary(values)
    secondary = values['SecondaryApplication'][0]
    scenes = []
    pairs = set()
    groups = {}
    level_groups = set()

    def group(application, address, reason, *, levels=False):
        groups.setdefault((application, address), []).append(reason)
        if levels:
            level_groups.add((application, address))

    def retain_trigger(trigger, reason):
        """Match TriggerGroup.get without invoking ActionSelector.get."""
        if trigger == 255:
            return 255
        if _record(snapshot, 202, trigger) is None:
            return 255
        group(202, trigger, reason)
        return trigger

    def get_action(trigger, raw_action, reason):
        """Return updated raw state and the ActionSelector getter result."""
        trigger = retain_trigger(trigger, reason)
        if trigger == 255:
            # The retained getter reports -1 but leaves its raw field intact.
            return trigger, raw_action, -1
        record = _record(snapshot, 202, trigger)
        group(202, trigger, reason, levels=True)
        if raw_action not in record.levels:
            return trigger, -1, -1
        pairs.add((trigger, raw_action))
        return trigger, raw_action, raw_action

    def set_action(trigger, raw_action, requested, reason):
        """Match ActionSelector.set, including absent-trigger preservation."""
        trigger = retain_trigger(trigger, reason)
        if trigger == 255:
            return trigger, raw_action
        record = _record(snapshot, 202, trigger)
        group(202, trigger, reason, levels=True)
        if requested not in record.levels:
            return trigger, -1
        pairs.add((trigger, requested))
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
    return groups, level_groups, tuple(sorted(pairs))


@dataclass(frozen=True)
class ResolvedSceneMetadata:
    snapshot: NativeEdltProjectSnapshot
    operations: tuple
    cache: SceneManagerCache
    requirements: str
    action_pairs: tuple[tuple[int, int], ...]
    group_reasons: str

    def as_dict(self):
        return {
            'format': 'cbus-native-edlt-scene-cache-v1',
            'profile': PROFILE,
            'cache': self.cache.as_dict(),
            'requirements': json.loads(self.requirements),
            'consumed_trigger_actions': [
                {'group': group, 'action': action}
                for group, action in self.action_pairs
            ],
            'group_reasons': json.loads(self.group_reasons),
            'metadata_provenance': 'one-admitted-native-project-xml-snapshot',
            'metadata_objects_created': False,
            'missing_objects_auto_created': False,
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
    missing_apps = sorted(required_apps - set(applications))
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
    extra_groups, extra_levels, action_pairs = _operation_facts(
        supplied, engine, snapshot, operations)
    for key, reasons in extra_groups.items():
        group_reasons.setdefault(key, []).extend(reasons)
    level_groups.update(extra_levels)

    cache_groups = []
    for (application, group), reasons in sorted(group_reasons.items()):
        if application not in applications:
            raise ValueError('Required native application is absent: '
                             + str(application))
        if group == 255:
            cache_groups.append(LifecycleGroup(
                application, 255, True, (False,) * 4, True, ()))
            continue
        record = _record(snapshot, application, group)
        if record is None:
            cache_groups.append(LifecycleGroup(application, group, False))
            continue
        facts = requirements_by_group.get((application, group), {}).get(
            'facts', {})
        needs_images = bool(facts.get('dynamic_images_if_present'))
        if needs_images and not record.dynamic_images_known:
            raise ValueError(
                'Consumed dynamic image metadata is not derivable from DBGETXML; '
                f'application {application} group {group} requires project/DLTP images')
        cache_groups.append(LifecycleGroup(
            application, group, True,
            record.dynamic_images if needs_images else None,
            needs_images,
            record.levels if (application, group) in level_groups else None))
    if len(cache_groups) > 512:
        raise ValueError('Resolved eDLT scene cache exceeds 512 group facts')

    lifecycle = LifecycleCache(
        tuple(sorted(applications)), tuple(cache_groups))
    displays = tuple(CachedDisplay(row.address, row.tag, row.tag)
                     for row in snapshot.applications)
    virtual_apps = {row.application for row in cache_groups
                    if row.group == 255 and row.exists}
    group_lists = tuple(CachedGroupList(
        application.address, True,
        tuple(CachedDisplay(row.address, row.tag, row.tag)
              for row in application.groups)
        + ((CachedDisplay(255, '<Unused>', '<Unused>'),)
           if application.address in virtual_apps else ()))
        for application in snapshot.applications)
    application_cache = ApplicationCache(
        lifecycle, True, displays, group_lists)

    level_labels = []
    for group_address, action in action_pairs:
        group = _record(snapshot, 202, group_address)
        level = None if group is None else next(
            (row for row in group.level_records if row.address == action), None)
        if level is None:
            raise ValueError(
                f'Resolved trigger action disappeared: {group_address}/{action}')
        if not level.dynamic_labels_known:
            raise ValueError(
                'Consumed trigger action image metadata is not derivable from '
                f'DBGETXML: group {group_address} action {action}')
        level_labels.append(SceneLevelLabels(
            group_address, action,
            tuple(SceneDynamicLabel(*row) for row in level.dynamic_labels)))
    cache = SceneManagerCache(application_cache, tuple(level_labels))
    reasons = _json([
        {'application': application, 'group': group,
         'reasons': list(dict.fromkeys(group_reasons[(application, group)]))}
        for application, group in sorted(group_reasons)
    ])
    return ResolvedSceneMetadata(
        snapshot, operations, cache, _json(requirements), action_pairs, reasons)


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
            self.resolved.cache, self.validate,
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
            'metadata_mutation_planned': False,
            'mutation_required': bool(self.scene_plan.changes),
            'stale_project_and_pp_rechecked_before_apply': True,
            'connected_staging_rollback': True,
            'rollback_after_pp_save_attempt': False,
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
    """Single-use automatic-cache SceneManager transaction."""
    def __init__(self, client, editor, *, programmer=None):
        from .edlt_scene_manager_cli import SceneCLIEditor
        if type(editor) is not SceneCLIEditor:
            raise ValueError('Expected a SceneCLIEditor')
        self.client, self.editor = client, editor
        self.database = NativeDatabase(client)
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
            'complete': False, 'saved': False,
            'metadata_mutation_attempted': False,
            'pp_mutation_attempted': False,
            'pp_readback_verified': False,
            'pp_save_attempted': False, 'pp_save_confirmed': False,
            'pp_save_outcome_uncertain': False,
            'persistence_verified': False,
            'rollback_attempted': False, 'rollback_verified': False,
            'rollback_errors': [], 'pp_state_uncertain': False,
            'database_state_uncertain': False,
            'database_persistence': 'not-attempted',
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
        uncertain = (self._evidence['pp_save_attempted']
                     and not self._evidence['pp_save_confirmed'])
        staging = self._evidence.get('staging_evidence') or {}
        rollback_verified = bool(staging.get('rollback_verified'))
        rollback_attempted = bool(staging.get('attempted_parameters'))
        rollback_errors = list(staging.get('rollback_errors', ()))
        self._evidence.update(
            complete=False, saved=False, error=_error(error),
            state='uncertain' if uncertain else 'stopped',
            rollback_attempted=rollback_attempted,
            rollback_verified=rollback_verified,
            rollback_errors=rollback_errors,
            pp_save_outcome_uncertain=uncertain,
            pp_state_uncertain=uncertain or (rollback_attempted
                                             and not rollback_verified),
            database_state_uncertain=uncertain,
            database_persistence=(
                'uncertain' if uncertain else
                'save-confirmed-verification-incomplete'
                if self._evidence['pp_save_confirmed'] else
                'original-state-verified-after-rollback'
                if rollback_verified else 'not-saved'),
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

    def apply(self, plan):
        self._start('apply')
        try:
            self._issued(plan)
            if id(plan) in self._consumed:
                raise ValueError('This plan already had an apply attempt')
            self._consumed.add(id(plan))
            self._evidence['plan'] = plan.as_dict()
            self._fresh(plan, exact=True)
            snapshot = plan.resolved.snapshot
            lock = f'//{snapshot.project}/{snapshot.network}'
            self._evidence.update(state='pp', pp_mutation_attempted=True)
            with self.programmer.load(lock, database_address(plan.unit)) as session:
                if self.editor.snapshot(session.values()) != snapshot.value_map():
                    raise ValueError(
                        'PP source changed after automatic scene metadata planning')
                try:
                    staged = self.editor.engine.apply(session, plan.scene_plan)
                except BaseException:
                    if isinstance(self.editor.last_evidence, dict):
                        self._evidence['staging_evidence'] = self.editor.last_evidence
                    raise
                self._evidence['staging_evidence'] = staged
                self._evidence['pp_readback_verified'] = bool(
                    staged.get('verified'))
                self._evidence.update(state='pp_save', pp_save_attempted=True)
                session.save_to_source()
                self._evidence['pp_save_confirmed'] = True

            self._evidence['state'] = 'verify'
            final_text = self._xml(snapshot.project)
            final = _snapshot(final_text, plan.unit, self.editor.engine)
            expected = {**plan.scene_plan.expected, **plan.scene_plan.changes}
            if final.value_map() != expected:
                raise RuntimeError(
                    'Persisted native PP differs from the scene transaction')
            if not self._metadata_equal(snapshot, final):
                raise RuntimeError(
                    'Native project metadata changed during the scene transaction')
            self._evidence.update(
                state='verified_saved', complete=True, saved=True,
                database_persistence='verified-after-dbgetxml',
                persistence_verified=True,
                existing_metadata_preserved=True,
                unrelated_unit_and_network_metadata_preserved=True,
                parameters_sha256=_digest(_json({
                    name: list(value) for name, value in final.values
                })),
            )
            return self._finish()
        except BaseException as error:
            self._fail(error)
