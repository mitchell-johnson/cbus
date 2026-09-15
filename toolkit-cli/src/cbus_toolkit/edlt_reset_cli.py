"""CLI inputs for the bounded original eDLT Reset Unit controls."""
from __future__ import annotations
from pathlib import Path


def options(parser):
    parser.add_argument('--metadata', type=Path, required=True,
                        help='Complete ordered application/group cache and lifecycle facts')
    parser.add_argument('--active-tab', choices=('widgets', 'general', 'standby', 'colour'), required=True,
                        help='Selected Toolkit tab when the reset control is invoked')
    parser.add_argument('--binding-variant', choices=('base-c3', 'audited-local-wiring'), required=True,
                        help='Verified local control setup; see the Reset controls scope documentation')
    parser.add_argument('--dirty-parameter', action='append', default=[], metavar='NAME',
                        help='Declare a previously changed raw parameter; repeat for distinct names')


def editor(args):
    from .edlt_global_cli import spec
    from .edlt_reset import EdltResetControls
    return EdltResetControls(spec(args))


def settings(args):
    from .edlt_application_cache import ApplicationCache
    from .edlt_global_cli import read_json
    dirty = tuple(args.dirty_parameter)
    if len(dirty) > 874 or len(set(dirty)) != len(dirty):
        raise ValueError('Declare at most 874 distinct dirty parameter names')
    return {'metadata': ApplicationCache.from_dict(read_json(args.metadata, limit=16*1024*1024)),
            'active_tab': args.active_tab, 'binding_variant': args.binding_variant,
            'dirty_parameters': dirty}


def offline(args):
    from .edlt_global_cli import read_json
    instance = editor(args)
    raw = instance.read_raw_document(read_json(args.file, limit=1024*1024))
    return instance.plan(raw, **settings(args)).as_dict(), 0
