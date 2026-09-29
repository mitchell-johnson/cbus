"""CLI input boundary for one ordered eDLT parent transaction."""
from __future__ import annotations

import json
from pathlib import Path


class ParentTransactionSaveError(RuntimeError):
    """A verified PP transaction reached SAVE, but persistence is unconfirmed."""

    def __init__(self, cause, evidence):
        from .edlt import _apply_error_text

        self.cause = cause
        self.details = {
            'saved': False,
            'save_attempted': True,
            'save_outcome_uncertain': True,
            'pp_state_uncertain': True,
            'database_state_uncertain': True,
            'automatic_retries': 0,
        }
        for name in ('programming_cleanup_errors', 'cgate_cleanup_errors'):
            try:
                value = getattr(cause, name, None)
                if value is not None:
                    setattr(self, name, value)
            except BaseException:
                pass
        super().__init__(_apply_error_text(cause))


def record_save_failure(error, result, destination):
    """Attach conservative evidence without retrying an uncertain SAVE."""
    from .edlt import _apply_error_text

    evidence = {
        **result,
        'failure_phase': 'database_save',
        'operation_completed': False,
        'staging_verified': True,
        'pp_readback_verified_before_save': True,
        'pp_state_uncertain': True,
        'database_state_uncertain': True,
        'database_persistence': 'uncertain',
        'persistence_verified': False,
        'saved': False,
        'save_attempted': True,
        'save_outcome_uncertain': True,
        'database_save_calls_attempted': 1,
        'destination': destination,
        'rollback_performed': False,
        'automatic_retries': 0,
        'save_error': {
            'type': type(error).__name__,
            'error': _apply_error_text(error),
        },
    }
    wrapped = (ParentTransactionSaveError(error, evidence)
               if isinstance(error, Exception) else error)
    try:
        wrapped.edlt_parent_transaction_evidence = evidence
    except BaseException:
        pass
    return wrapped


def options(parser, *, surface='manual'):
    if surface == 'offline':
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            '--metadata', type=Path,
            help=('Caller-supplied retained lifecycle, complete application '
                  'or complete SceneManager cache JSON'))
        source.add_argument(
            '--project-xml', type=Path,
            help='Exact native DBGETXML project snapshot used to derive metadata')
        parser.add_argument(
            '--unit', help='Selected //PROJECT/network/p/unit; required with --project-xml')
    elif surface == 'native':
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            '--metadata', type=Path,
            help=('Caller-supplied retained lifecycle, complete application '
                  'or complete SceneManager cache JSON'))
        source.add_argument(
            '--auto-metadata', action='store_true',
            help='Derive and create guarded metadata from the live project snapshot')
        parser.add_argument(
            '--exclusive-project', action='store_true',
            help='Declare exclusive closed-project editing; required with --auto-metadata')
        parser.add_argument(
            '--backup-project',
            help='New backup project name for an automatic metadata apply')
    else:
        parser.add_argument(
            '--metadata', type=Path, required=True,
            help=('Caller-supplied retained lifecycle, complete application '
                  'or complete SceneManager cache JSON'))
    if surface in ('offline', 'native'):
        presentation_options(parser)
    parser.add_argument(
        '--operations', type=Path, required=True,
        help=('JSON array of 2..22 ordered supported widget/settings, one '
              'SceneManager projection, or operation-1 Reset '
              'operations; see edlt-parent-transaction.md'))


def _read_operations(path, *, limit=256 * 1024):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate key in parent transaction operation: ' + key)
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError('Non-finite JSON number in parent transaction: ' + value)

    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Parent transaction operations exceed 256 KiB')
    return json.loads(
        raw, object_pairs_hook=unique, parse_constant=nonfinite)


def settings(args):
    from .edlt_parent_transaction import normalize_operations
    return {
        'metadata': metadata(args.metadata),
        'operations': normalize_operations(_read_operations(args.operations)),
    }


def metadata(path, *, limit=16 * 1024 * 1024):
    """Read one bounded parent metadata contract without weakening JSON."""
    from .edlt_application_cache import ApplicationCache
    from .edlt_lifecycle import LifecycleCache
    from .edlt_scene_manager import SceneManagerCache

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate key in parent transaction metadata: ' + key)
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError('Non-finite JSON number in parent transaction metadata: ' + value)

    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Parent transaction metadata exceeds 16 MiB')
    document = json.loads(
        raw, object_pairs_hook=unique, parse_constant=nonfinite)
    if (isinstance(document, dict) and
            document.get('format') == 'cbus-edlt-application-cache-v1'):
        return ApplicationCache.from_dict(document)
    if (isinstance(document, dict) and
            document.get('format') ==
            'cbus-edlt-scene-manager-cache-v1'):
        return SceneManagerCache.from_dict(document)
    return LifecycleCache.from_dict(document)


def operations(args):
    """Read the one strict operation document shared by all surfaces."""
    from .edlt_parent_transaction import normalize_operations
    return normalize_operations(_read_operations(args.operations))


def read_project_xml(path, *, limit=16 * 1024 * 1024):
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError('Native project XML must be nonempty and at most 16 MiB')
    return raw.decode('utf-8', 'strict')


def presentation_options(parser):
    """Automatic-metadata display preferences and the Toolkit DLTP index."""
    parser.add_argument(
        '--display-preferences', type=Path,
        help=('cbus-edlt-display-preferences-v1 JSON with the eDLT registry '
              'DWORDs; applies FormattedDisplay and SortMode list order. '
              'Omit to keep the TagName view in DBGETXML order'))
    parser.add_argument(
        '--toolkit-dltp-dir', type=Path,
        help=('Toolkit application directory containing Images/DLTP/Index.txt; '
              'resolves ICON dynamic-label images'))
    parser.add_argument(
        '--toolkit-dltp-sha256',
        help='Required SHA-256 of the Toolkit DLTP Index.txt bytes')


def presentation(args):
    """Return plan keyword arguments; reject them without automatic metadata."""
    preferences = getattr(args, 'display_preferences', None)
    directory = getattr(args, 'toolkit_dltp_dir', None)
    digest = getattr(args, 'toolkit_dltp_sha256', None)
    if (directory is None) != (digest is None):
        raise ValueError('--toolkit-dltp-dir and --toolkit-dltp-sha256 must be supplied together')
    automatic = (getattr(args, 'project_xml', None) is not None
                 or getattr(args, 'auto_metadata', False))
    if not automatic and (preferences is not None or directory is not None):
        raise ValueError('--display-preferences and --toolkit-dltp-dir require '
                         '--project-xml or --auto-metadata')
    result = {'display_preferences': None, 'dltp_index': None}
    if preferences is not None:
        from .edlt_display_model import EdltDisplayPreferences
        from .edlt_global_cli import read_json
        result['display_preferences'] = EdltDisplayPreferences.from_dict(
            read_json(preferences, limit=64 * 1024))
    if directory is not None:
        from .edlt_dltp_index import load_dltp_index
        result['dltp_index'] = load_dltp_index(directory, expected_sha256=digest)
    return result
