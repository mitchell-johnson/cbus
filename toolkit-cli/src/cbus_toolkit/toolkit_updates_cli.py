"""CLI boundary for a printed download link and unverified catalogue candidates."""
from __future__ import annotations

from pathlib import Path

from .toolkit_updates import HTTPSCatalogueTransport, ToolkitUpdateCatalogue, catalogue_request, toolkit_download_link, _timeout


def options(commands):
    link = commands.add_parser('update-link', help='Print the Toolkit download-page link without opening a browser')
    link.add_argument('--state', type=Path, help='Explicit complete preference-state JSON; default is observed constructor state')
    catalogue = commands.add_parser('update-catalogue', help='Query unverified server-assigned candidates; does not establish update availability')
    catalogue.add_argument('--installed-version', required=True, help='Explicit vendor version string, sent unchanged without comparison')
    catalogue.add_argument('--timeout', type=float, default=15, help='Seconds per blocking socket operation (0 < timeout <= 300)')


def catalogue_transport():
    return HTTPSCatalogueTransport()


def run(args):
    args._update_catalogue = None
    if args.area == 'update-link':
        if args.state is None:
            from .toolkit_preferences_initial_state import constructor_state
            values = constructor_state()['values']; source = 'observed-constructor-state'
        else:
            from .toolkit_preferences_cli import read_state
            values, _ = read_state(args.state); source = 'explicit-state-file'
        result = toolkit_download_link(values).as_dict()
        result['preference_source'] = source
        result['current_host_preferences_read'] = False
        return result, 0
    if args.area != 'update-catalogue':
        raise ValueError('Unsupported update command')
    catalogue_request(args.installed_version); _timeout(args.timeout)
    editor = ToolkitUpdateCatalogue(catalogue_transport())
    args._update_catalogue = editor
    result = editor.query(args.installed_version, timeout=args.timeout)
    return result.as_dict(), 0 if result.complete else 1


def error_payload(error, args):
    if getattr(args, 'area', None) != 'update-catalogue': return {}
    editor = getattr(args, '_update_catalogue', None)
    # Use the current operation's identity, including exceptions that reject an
    # evidence attribute. Attached dictionaries from another operation are ignored.
    if editor is not None and editor.last_outcome is not None and editor.last_outcome.cause is error:
        return {'toolkit_update_evidence': editor.last_outcome.as_dict()}
    return {}
