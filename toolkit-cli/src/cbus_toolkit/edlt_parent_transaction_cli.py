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


def options(parser):
    parser.add_argument(
        '--metadata', type=Path, required=True,
        help='Caller-supplied retained lifecycle cache JSON')
    parser.add_argument(
        '--operations', type=Path, required=True,
        help='JSON array of 2..22 ordered measurement, lighting or activation operations')


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
    from .cli import _edlt_lifecycle_metadata
    from .edlt_parent_transaction import normalize_operations
    return {
        'metadata': _edlt_lifecycle_metadata(args.metadata),
        'operations': normalize_operations(_read_operations(args.operations)),
    }
