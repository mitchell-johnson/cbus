"""One-shot scene capture/save and broadcast CLI composition."""
from __future__ import annotations
from pathlib import Path

EVIDENCE = 'edlt_scene_live_evidence'


def options(parser, *, broadcast=False):
    if broadcast:
        parser.add_argument('file', type=Path, help='Complete exact-profile eDLT PP source export')
    parser.add_argument('--metadata', type=Path, required=True, help='Scene Manager application and group cache facts')
    parser.add_argument('--network', required=True, help='Explicit live target network, such as //PROJECT/254')
    parser.add_argument('--scene', type=int, choices=range(1, 9), required=True)
    if broadcast:
        parser.add_argument('--scope', choices=('current', 'all'), required=True)
        parser.add_argument('--item', type=int, help='One-based retained item; required with --scope current')


def trigger_options(parser):
    parser.add_argument('file', type=Path,
                        help='Identity-bearing KEYGL5 5.5.00 / 5055EDL PP export')
    parser.add_argument('--metadata', type=Path, required=True, help='Scene Manager application and group cache facts')
    parser.add_argument('--network', required=True, help='Explicit live target network, such as //PROJECT/254')
    parser.add_argument('--scene', type=int, choices=range(1, 9), required=True)
    parser.add_argument('--force', action='store_true', help='Request native Trigger Control FORCE behavior')


def settings(args):
    from .edlt_global_cli import read_json
    from .edlt_scene_manager import SceneManagerCache
    return {'metadata': SceneManagerCache.from_dict(read_json(args.metadata, limit=16*1024*1024)),
            'scene': args.scene}


class SceneLiveCommandError(RuntimeError):
    def __init__(self, cause, evidence):
        from .edlt import _apply_error_text
        self.cause = cause
        self.details = {EVIDENCE: evidence}
        setattr(self, EVIDENCE, evidence)
        for name in ('programming_cleanup_errors', 'cgate_cleanup_errors'):
            try:
                value = getattr(cause, name, None)
                if value is not None: setattr(self, name, value)
            except BaseException: pass
        super().__init__(_apply_error_text(cause))


class IncompleteSceneCapture(ValueError):
    def __init__(self, evidence):
        setattr(self, EVIDENCE, evidence)
        super().__init__('Scene capture is incomplete; inspect its observations before starting a new capture')


class SceneCaptureCLIEditor:
    def __init__(self, spec, client, *, network):
        from .edlt_scene_manager import EdltSceneManager
        from .edlt_scene_live import NativeEdltSceneLive
        self.engine = EdltSceneManager(spec)
        self.live = NativeEdltSceneLive(self.engine, client, network=network)
        self.last_evidence = None

    def configure(self, session, *, metadata, scene):
        self.last_evidence = None
        self.engine.last_evidence = None
        capture = None
        phase = 'identity'
        try:
            self.engine.common._verify_identity(session)
            phase = 'load'
            loaded = self.engine.load(session.values(), metadata=metadata)
            phase = 'capture'
            outcome = self.live.capture(loaded, scene=scene)
            capture = outcome.as_dict()
            self.last_evidence = {'live_capture': capture, 'verified': False,
                                  'attempted_parameters': [], 'pp_state_uncertain': False,
                                  'saved': False, 'automatic_retries': 0}
            if not outcome.complete:
                if self.live.last_error is not None:
                    raise self.live.last_error
                raise IncompleteSceneCapture(self.last_evidence)
            phase = 'prepare_save'
            plan = self.engine.prepare_save(outcome.state)
            phase = 'apply'
            result = self.engine.apply(session, plan)
            self.last_evidence = {**result, 'live_capture': capture}
            return self.last_evidence
        except BaseException as error:
            if capture is None and phase == 'capture':
                capture = self.live.last_evidence
            if capture is not None:
                staged = self.engine.last_evidence if phase == 'apply' else None
                evidence = {**(staged if isinstance(staged, dict) else {
                                'verified': False, 'attempted_parameters': [], 'pp_state_uncertain': False}),
                            'live_capture': capture, 'capture_pipeline_phase': phase,
                            'saved': False, 'automatic_retries': 0}
                self.last_evidence = evidence
                wrapped = SceneLiveCommandError(error, evidence) if isinstance(error, Exception) else error
                try: setattr(wrapped, EVIDENCE, evidence)
                except BaseException: pass
                if wrapped is not error: raise wrapped from error
            raise


def editor(args, client):
    from .edlt_global_cli import spec
    return SceneCaptureCLIEditor(spec(args), client, network=args.network)


def error_payload(error, args=None):
    try: evidence = getattr(error, EVIDENCE, None)
    except BaseException: evidence = None
    if not isinstance(evidence, dict): evidence = getattr(args, '_scene_live_evidence', None)
    return {EVIDENCE: evidence} if isinstance(evidence, dict) else {}


def broadcast(args, client_factory, ssl_context):
    from .edlt_global_cli import spec, read_parameters
    from .edlt_scene_manager import EdltSceneManager
    from .edlt_scene_live import NativeEdltSceneLive
    args._scene_live_evidence = None
    if args.scope == 'current' and args.item is None:
        raise ValueError('--scope current requires an explicit --item')
    configured = settings(args)
    manager = EdltSceneManager(spec(args))
    state = manager.load(read_parameters(args.file), metadata=configured['metadata'])
    client = client_factory(args.host, args.port or (20123 if args.tls else 20023),
                            timeout=args.timeout, ssl_context=ssl_context)
    live = NativeEdltSceneLive(manager, client, network=args.network)
    selection = {'scene': args.scene, 'scope': args.scope, 'item': args.item}
    live.validate_broadcast(state, **selection)
    result = None
    try:
        with client:
            result = live.broadcast(state, **selection).as_dict()
            args._scene_live_evidence = result
        return result, int(not result['complete'])
    except BaseException as error:
        evidence = ({**result, 'operation_completed': False, 'failure_phase': 'connection_cleanup'}
                    if result is not None else live.last_evidence)
        if isinstance(evidence, dict):
            args._scene_live_evidence = evidence
            wrapped = SceneLiveCommandError(error, evidence) if isinstance(error, Exception) else error
            try: setattr(wrapped, EVIDENCE, evidence)
            except BaseException: pass
            if wrapped is not error: raise wrapped from error
        raise


def trigger(args, client_factory, ssl_context):
    """Resolve a retained scene binding, then submit exactly one Trigger event."""
    from .edlt_global_cli import spec, read_json
    from .edlt_scene_manager import EdltSceneManager
    from .edlt_scene_trigger import NativeEdltSceneTrigger
    args._scene_live_evidence = None
    manager = EdltSceneManager(spec(args))
    configured = settings(args)
    state = manager.load_export(read_json(args.file), metadata=configured['metadata'])
    client = client_factory(args.host, args.port or (20123 if args.tls else 20023),
                            timeout=args.timeout, ssl_context=ssl_context)
    sender = NativeEdltSceneTrigger(manager, client, network=args.network)
    # Complete all source/cache/route validation before opening a connection.
    sender.plan(state, scene=args.scene, force=args.force)
    result = None
    try:
        with client:
            result = sender.trigger(state, scene=args.scene, force=args.force).as_dict()
            args._scene_live_evidence = result
        return result, int(not result['complete'])
    except BaseException as error:
        evidence = sender.last_evidence
        if result is not None:
            evidence = {**result, 'operation_completed': False,
                        'failure_phase': 'connection_cleanup'}
        if isinstance(evidence, dict):
            args._scene_live_evidence = evidence
            wrapped = SceneLiveCommandError(error, evidence) if isinstance(error, Exception) else error
            try:
                setattr(wrapped, EVIDENCE, evidence)
            except BaseException:
                pass
            if wrapped is not error:
                raise wrapped from error
        raise
