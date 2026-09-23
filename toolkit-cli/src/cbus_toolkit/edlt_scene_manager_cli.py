"""CLI adapters for one retained scene editing sequence and its final save."""
from __future__ import annotations
import json
from pathlib import Path


def options(parser, *, state_only=False):
    parser.add_argument('--metadata', type=Path, required=True, help='Scene Manager application and DynamicAll cache facts')
    parser.add_argument('--operations', type=Path, required=True, help='JSON array of up to 256 ordered scene operations')
    parser.add_argument('--validate', action='store_true', help='Run the original scene validation getters before preparing the save')
    if state_only:
        parser.add_argument('--list-groups', type=int, choices=range(1, 9), action='append', default=[], metavar='SCENE',
                            help='Include available cached groups for a scene after the edit sequence')


def settings(args):
    from .edlt_global_cli import read_json
    from .edlt_scene_manager import EdltSceneManager, SceneManagerCache, MAX_OPERATIONS
    cache = SceneManagerCache.from_dict(read_json(args.metadata, limit=16*1024*1024))
    operations = read_json(args.operations, limit=512*1024)
    if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
        raise ValueError('Scene operations must be an array of at most 256 entries')
    # Reject malformed operation fields before a native programming session.
    operations = tuple(EdltSceneManager._operation(row) for row in operations)
    return {'metadata': cache, 'operations': operations, 'validate': args.validate}


class IncompleteSceneEdit(ValueError):
    def __init__(self, evidence):
        self.edlt_scene_manager_evidence = evidence
        super().__init__('Scene capacity stopped the edit sequence; inspect its partial state and start a new complete sequence before saving')


class SceneCLIEditor:
    """Keep the same engine, loaded objects and evidence across CLI stages."""
    def __init__(self, spec):
        from .edlt_scene_manager import EdltSceneManager
        self.engine = EdltSceneManager(spec)

    @property
    def last_evidence(self): return self.engine.last_evidence

    @last_evidence.setter
    def last_evidence(self, value): self.engine.last_evidence = value

    def snapshot(self, values): return self.engine.snapshot(values)

    def sequence(self, values, *, metadata, operations, validate=False):
        self.last_evidence = None
        loaded = self.engine.load(values, metadata=metadata)
        outcome = self.engine.edit(loaded, operations=operations)
        state = outcome.state
        validation = self.engine.validate(state) if validate else None
        if validation is not None: state = validation.state
        return state, outcome, validation

    def plan(self, values, *, metadata, operations, validate=False):
        state, outcome, _validation = self.sequence(values, metadata=metadata, operations=operations, validate=validate)
        if not outcome.complete:
            evidence = {**outcome.as_dict(), 'state': state.as_dict(), 'verified': False,
                        'saved': False, 'attempted_parameters': [], 'pp_state_uncertain': False,
                        'automatic_retries': 0}
            self.last_evidence = evidence
            raise IncompleteSceneEdit(evidence)
        return self.engine.prepare_save(state)

    def configure(self, session, **kwargs):
        self.last_evidence = None
        self.engine.common._verify_identity(session)
        plan = self.plan(session.values(), **kwargs)
        return self.engine.apply(session, plan)


def editor(args):
    from .edlt_global_cli import spec
    return SceneCLIEditor(spec(args))


def offline(args, *, state_only=False):
    from .edlt_global_cli import read_parameters
    instance = editor(args)
    values, configured = read_parameters(args.file), settings(args)
    if not state_only: return instance.plan(values, **configured).as_dict(), 0
    state, outcome, validation = instance.sequence(values, **configured)
    selected = tuple(args.list_groups)
    if len(selected) != len(set(selected)):
        raise ValueError('List each scene at most once for available groups')
    groups = {str(slot): [item.as_dict() for item in instance.engine.available_groups(state, scene=slot)]
              for slot in selected}
    return {'format': 'cbus-edlt-scene-manager-cli-state-v1', 'state': state.as_dict(),
            'complete': outcome.complete, 'operation_results': [json.loads(row) for row in outcome.operation_results],
            'validation': None if validation is None else {key: value for key, value in validation.as_dict().items() if key != 'state'},
            'available_groups': groups, 'saved': False, 'export_is_review_only': True}, 0
