"""CLI adapters for DLT profiles, classic label controls and project TEXT labels."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _slot_variant(text):
    slot, separator, value = text.partition('=')
    if not separator or not slot.strip().isdecimal() or not value.strip().isdecimal():
        raise ValueError('--variant uses SLOT=VARIANT, for example 3=2')
    return int(slot), int(value)


def variant_options(parser):
    parser.add_argument('--variant', action='append', default=[], type=_slot_variant, metavar='SLOT=VARIANT',
                        help='Key slot 1..8 and Toolkit label variant 1..4; repeat for several slots')
    parser.add_argument('--block-dynamic-updates', choices=('yes', 'no'),
                        help='Block/allow dynamic updates using the original inverse EnableDynamicLabels bit')


def variants(args):
    selected = {}
    for slot, value in args.variant:
        if slot in selected:
            raise ValueError(f'Key slot {slot} was selected more than once')
        selected[slot] = value
    return selected


def options(commands):
    """Register the offline ``dlt`` command group."""
    dlt = commands.add_parser('dlt', help='Inspect DLT/eDLT profiles and edit classic DLT label controls and text')
    dlt.add_argument('--spec-dir', type=Path, default=os.environ.get('CBUS_UNITSPEC_DIR'))
    ops = dlt.add_subparsers(dest='action', required=True)
    p = ops.add_parser('profiles', help='Show the profile registry, or every workflow decision for one identity')
    p.add_argument('--unit-type')
    p.add_argument('--firmware')
    p.add_argument('--catalog-number')
    from .dlt_project_cli import options as text_options
    text_options(ops)
    labels = ops.add_parser('labels', help='Show or plan classic DLT variants and dynamic-update controls offline')
    lops = labels.add_subparsers(dest='labels_action', required=True)
    for action in ('show', 'plan'):
        p = lops.add_parser(action)
        source = p.add_mutually_exclusive_group(required=True)
        source.add_argument('--file', type=Path, help='PP export (cbus-cli-parameters-v1) or bare parameter mapping')
        source.add_argument('--project-xml', type=Path, help='Native DBGETXML Installation document')
        p.add_argument('--unit', help='//PROJECT/network/p/unit inside --project-xml')
        p.add_argument('--unit-type', help='Required for a bare parameter mapping')
        p.add_argument('--firmware', help='Required with --unit-type for a bare mapping')
        p.add_argument('--catalog-number')
        if action == 'plan':
            variant_options(p)


def _editor(spec_dir, unit_type):
    from .dlt_controls import ClassicDltControls
    from .dlt_profiles import profile_for
    from .unitspec import UnitSpecStore
    if spec_dir is None:
        raise ValueError('Use --spec-dir or CBUS_UNITSPEC_DIR for decoded vendor specifications')
    return ClassicDltControls(UnitSpecStore(spec_dir).load(profile_for(unit_type).spec_filename), unit_type)


def _source(args):
    from .dlt_labels import project_unit
    from .dlt_project_cli import _read
    if args.project_xml is not None:
        if args.unit is None:
            raise ValueError('--project-xml requires --unit //PROJECT/network/p/unit')
        return project_unit(_read(args.project_xml, 16 * 1024 * 1024), args.unit)
    if args.unit is not None:
        raise ValueError('--unit applies only to --project-xml')
    values = _read_json(args.file)
    if not isinstance(values, dict):
        raise ValueError('Expected a PP parameter mapping or export snapshot')
    if 'format' in values:
        if values.get('format') != 'cbus-cli-parameters-v1':
            raise ValueError('Snapshot format differs from cbus-cli-parameters-v1')
        identity = tuple(values.get(key) for key in ('unit_type', 'firmware', 'catalog_number'))
        if any(value is not None and getattr(args, key) not in (None, value) for key, value in
               zip(('unit_type', 'firmware', 'catalog_number'), identity)):
            raise ValueError('Command-line identity differs from the snapshot identity')
        values = values.get('parameters')
        if not isinstance(values, dict):
            raise ValueError('Snapshot requires a parameter mapping')
        return identity, values
    if args.unit_type is None or args.firmware is None:
        raise ValueError('A bare parameter mapping requires --unit-type and --firmware')
    return (args.unit_type, args.firmware, args.catalog_number), values


def _read_json(path):
    from .dlt_project_cli import _read
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('Non-finite JSON number: ' + value)
    return json.loads(_read(path, 1024 * 1024), object_pairs_hook=unique, parse_constant=nonfinite)


def offline(args):
    if args.action == 'text':
        from .dlt_project_cli import offline as text_offline
        return text_offline(args)
    from .dlt_profiles import lookup, registry
    if args.action == 'profiles':
        if args.unit_type is None:
            if args.firmware is not None or args.catalog_number is not None:
                raise ValueError('--firmware and --catalog-number require --unit-type')
            return registry(), 0
        return lookup(args.unit_type, args.firmware, args.catalog_number), 0
    from .dlt_labels import WORKFLOW
    from .dlt_profiles import require
    identity, values = _source(args)
    require(WORKFLOW, *identity, message='Unit identity is not an admitted classic DLT label-variant profile')
    editor = _editor(args.spec_dir, identity[0])
    identity = editor.check_identity(*identity)
    if args.labels_action == 'show':
        return editor.show(values, identity), 0
    if args.block_dynamic_updates is not None:
        return editor.plan_controls(values, variants=variants(args), identity=identity,
                                    block_dynamic_updates=args.block_dynamic_updates == 'yes').as_dict(), 0
    return editor.plan(values, variants=variants(args), identity=identity).as_dict(), 0


def native_options(unops):
    p = unops.add_parser('dlt-labels', help='Show or set classic DLT variants and dynamic-update controls')
    p.add_argument('--spec-dir', type=Path, default=os.environ.get('CBUS_UNITSPEC_DIR'))
    p.add_argument('--show', action='store_true', help='Report the per-slot variants without editing')
    p.add_argument('--plan', dest='dlt_plan', type=Path, help='Apply a saved classic DLT variant or control plan')
    variant_options(p)


def native(args, session):
    """Return (result, edited) for the ``cgate unit ... dlt-labels`` action."""
    from .dlt_labels import DltLabelPlan
    from .dlt_controls import DltControlPlan, FORMAT as CONTROL_FORMAT
    editor = _editor(args.spec_dir, session.unit_type)
    identity = editor._verify_profile(session)
    editor._verify_session(session)
    selected = variants(args)
    control = args.block_dynamic_updates
    if args.show:
        if selected or control is not None or args.dlt_plan is not None:
            raise ValueError('--show cannot be combined with --variant, --block-dynamic-updates or --plan')
        return editor.show(session.values(), identity), False
    if args.dlt_plan is not None:
        if selected or control is not None:
            raise ValueError('--plan cannot be combined with --variant or --block-dynamic-updates')
        data = _read_json(args.dlt_plan)
        if isinstance(data, dict) and data.get('format') == CONTROL_FORMAT:
            return editor.apply_controls(session, DltControlPlan.from_dict(data)), True
        return editor.apply(session, DltLabelPlan.from_dict(data)), True
    if control is not None:
        return editor.configure_controls(session, block_dynamic_updates=control == 'yes', variants=selected), True
    if not selected:
        raise ValueError('Supply --variant SLOT=VARIANT, --block-dynamic-updates yes|no, --plan or --show')
    return editor.configure(session, variants=selected), True
