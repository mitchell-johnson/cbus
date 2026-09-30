"""Owned closed-network durability proof for one synthetic terminal PP image.

This does not call template Apply, the original Save validators, or a device.
It starts a fresh LocalCGate from explicitly supplied existing runtime files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
from uuid import uuid4

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.edlt import CRC_RANGES, _render
from cbus_toolkit.edlt_lifecycle import LifecycleCache
from cbus_toolkit.edlt_template_model_stage import EdltTemplateModelStage, _sha
from cbus_toolkit.edlt_template_terminal_stage import EdltTemplateTerminalStage
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitSpecStore
from research.local_cgate import LocalCGate


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def error_record(error):
    try: message = str(error)[:1024]
    except BaseException: message = '<unprintable exception>'
    return {'type': type(error).__name__, 'message': message}


def cleanup(evidence, tasks):
    """Always attempt owned cleanup, preserving an active operation failure."""
    primary, first = sys.exception(), None
    for label, action in tasks:
        try: action()
        except BaseException as error:
            evidence.setdefault('cleanup_errors', []).append({'operation': label, **error_record(error)})
            if first is None: first = error
    if first is not None and primary is None: raise first


def source_hashes(args, spec):
    root = Path(__file__).resolve().parents[1]
    paths = {str(Path(__file__).relative_to(root)): Path(__file__)}
    for relative in ('research/local_cgate.py', 'src/cbus_toolkit/edlt.py',
            'src/cbus_toolkit/edlt_lifecycle.py', 'src/cbus_toolkit/edlt_reset.py',
            'src/cbus_toolkit/edlt_template_model_stage.py',
            'src/cbus_toolkit/edlt_template_lifecycle_stage.py',
            'src/cbus_toolkit/edlt_template_terminal_stage.py',
            'src/cbus_toolkit/programming.py', 'src/cbus_toolkit/native.py',
            'src/cbus_toolkit/cgate.py', 'src/cbus_toolkit/unitspec.py'):
        paths[relative] = root / relative
    for name in spec.sources: paths['unitspec/' + name] = Path(args.spec_dir) / name
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def synthetic_source(model, baseline):
    """Fresh caller facts, without claiming original reset/control provenance."""
    raw = dict(baseline)
    raw.update(PrimaryApplication='56', SecondaryApplication='255', Application='56 255',
        SceneCount='0', Widget6WidgetType='2', Widget6WidgetByteValue1='48',
        Widget6WidgetByteValue6='42', Widget6WidgetByteValue12='0',
        Widget7WidgetType='7', Widget7WidgetByteValue1='237',
        Widget8WidgetType='255')
    for number in (*range(1, 6), *range(9, 22)):
        raw[f'Widget{number}WidgetType'] = '0'
    raw['SceneBucket'] = _render(tuple(([2, 0, 255, 255, 255] * 8) + [255] * 192))
    for number in range(1, 9): raw[f'Scene{number}StartAddress'] = str((number - 1) * 5)
    size = len(model.snapshot(baseline)['StaticTextString0'])
    raw['StaticTextString0'] = _render(tuple(b'OWNED TERMINAL'.ljust(size, b'\0')))
    requirements = model._lifecycle.requirements(raw).as_dict()
    cache = LifecycleCache.from_dict({'format': 'cbus-edlt-lifecycle-cache-v1',
        'applications': [56, 57, 127, 136, 172, 202, 203, 255],
        'groups': [{'application': row['application'], 'group': row['group'], 'exists': True,
            'dynamic_images': [] if row['group'] == 255 else [False] * 4,
            'levels': [0, 42, 255]} for row in requirements['groups']]})
    return raw, cache


def region_expected(model, values, start, count):
    data, masks = bytearray(count), bytearray(count)
    for name, value in values.items():
        for edit in model._lifecycle.common.codec.encode(name, value).edits:
            index = edit.address - start
            if 0 <= index < count:
                data[index] = (data[index] & ~edit.mask) | edit.value
                masks[index] |= edit.mask
    require(all(mask == 255 for mask in masks), 'Raw proof region includes unspecified bits')
    return bytes(data)


def raw_regions(session, model, receipt):
    codec = model._lifecycle.common.codec
    regions = [('widget6', codec.layout('Widget6WidgetType').address, 32),
        ('static_text0', codec.layout('StaticTextString0').address, 64),
        ('scene_bucket', codec.layout('SceneBucket').address, 232)]
    regions += [(name, codec.layout(name).address, 2) for name in CRC_RANGES]
    result = []
    for name, start, count in regions:
        reply = session.get_raw_data(start, count)
        rows = [line.split('RawData=', 1)[1] for line in reply.lines if 'RawData=' in line]
        require(len(rows) == 1, 'Expected one native RawData reply')
        actual = bytes.fromhex(rows[0])
        require(actual == region_expected(model, receipt.final, start, count), 'Raw mismatch: ' + name)
        result.append({'name': name, 'start': start, 'count': count, 'hex': actual.hex()})
    return result


def run(args, evidence):
    spec = UnitSpecStore(args.spec_dir).load('KEYGL5.xml')
    evidence['source_hashes_before'] = source_hashes(args, spec)
    model = EdltTemplateModelStage(spec)
    service = LocalCGate(args.vendor, java=args.java)
    evidence['service'] = service.report
    sentinel = None
    project = 'TM' + uuid4().hex[:6].upper()
    network, source = '//' + project + '/254', '/db//' + project + '/254/p/20'
    evidence.update(project=project, network=network, database_source=source)
    try:
        sentinel = socket.socket()
        sentinel.bind(('127.0.0.1', 0)); sentinel.listen(1); sentinel.settimeout(0.05)
        (service.work / 'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
        service.start()
        with CGateClient('127.0.0.1', service.port, timeout=30) as client:
            projects, database = NativeProjects(client), NativeDatabase(client)
            projects.operation('new', project)
            project_open = True
            try:
                database.create_network(project, 254, 'OwnedTerminal', 'Cni',
                    '127.0.0.1:' + str(sentinel.getsockname()[1]))
                database.create_unit(network, 20, 'eDLT', 'KEYGL5', '5.5.00', catalog_number='5055EDL')
                with Programmer(client).load(network, source) as session:
                    require((session.unit_type, session.firmware, session.catalog_number) ==
                        ('KEYGL5', '5.5.00', '5055EDL'), 'Unexpected native DB unit identity')
                    baseline = session.values()
                    raw, cache = synthetic_source(model, baseline)
                    upstream = model.stage(raw, metadata=cache)
                    terminal = EdltTemplateTerminalStage(model)
                    receipt = terminal.stage(upstream, current_source=raw, metadata=cache)
                    terminal.validate(receipt, current_source=raw, metadata=cache)
                    require(len(receipt.final) == 874 and len(receipt.crcs) == 5, 'Incomplete model image')
                    evidence.update(specification_sha256=receipt.specification_sha256,
                        source_sha256=_sha(raw), cache_sha256=receipt.cache_sha256,
                        terminal_receipt_sha256=_sha(receipt.as_dict()),
                        final_image_sha256=_sha(dict(receipt.final)),
                        crcs={name: list(value) for name, value in receipt.crcs.items()},
                        terminal_model_projection_passes=1, original_save_validation_verified=False)
                    numeric_baseline = model.snapshot(baseline)
                    require(model.snapshot(session.values()) == numeric_baseline, 'Fresh baseline changed')
                    changed = [name for name, value in receipt.final.items()
                        if value != numeric_baseline[name]]
                    for name in changed: session.set(name, receipt.rendered_parameters[name])
                    require(model.snapshot(session.values()) == dict(receipt.final), 'Complete staged readback mismatch')
                    evidence.update(staged_image_verified=True, parameters_compared=874,
                        crc_fields_compared=5, pp_parameters_written=len(changed))
                    evidence['staged_raw_regions'] = raw_regions(session, model, receipt)
                    state = client.command('GET ' + network + ' state')
                    require(any('state=new' in line for line in state.lines), 'Network must remain new before save')
                    evidence['network_state_before_save'] = 'new'
                    evidence['pp_save_attempted'] = True
                    evidence['pp_save_outcome_uncertain'] = True
                    reply = session.save_to_source()
                    require(reply.code == 200, 'PP save must return its successful native completion reply')
                    evidence.update(pp_save_confirmed=True, pp_save_outcome_uncertain=False,
                        pp_save_reply_code=reply.code)
                evidence['pp_session_cleanup_completed'] = True
                evidence['project_save_attempted'] = True
                evidence['project_save_outcome_uncertain'] = True
                projects.operation('save', project)
                evidence.update(project_save_confirmed=True, project_save_outcome_uncertain=False)
                projects.operation('close', project); project_open = False
                evidence['project_closed_after_save'] = True
                projects.operation('load', project); project_open = True
                evidence['project_reloaded_after_save'] = True
                evidence['fresh_pp_reload_attempted'] = True
                with Programmer(client).load(network, source) as session:
                    fresh = model.snapshot(session.values())
                    require(fresh == dict(receipt.final), 'Fresh project/PP reload does not match all 874 values')
                    require({name: fresh[name] for name in CRC_RANGES} == dict(receipt.crcs), 'Fresh CRC mismatch')
                    evidence['reloaded_raw_regions'] = raw_regions(session, model, receipt)
                    evidence.update(fresh_pp_reload_verified=True, parameters_compared_on_reload=874,
                        crcs_compared_on_reload=5, reloaded_image_sha256=_sha(fresh))
                state = client.command('GET ' + network + ' state')
                require(any('state=new' in line for line in state.lines), 'Network must remain new after reload')
                evidence['network_state_after_reload'] = 'new'
            finally:
                def delete_project():
                    projects.operation('delete', project)
                    evidence['disposable_project_deleted'] = True
                tasks = [('delete disposable project', delete_project)]
                if project_open: tasks.insert(0, ('close disposable project', lambda: projects.operation('close', project)))
                cleanup(evidence, tasks)
    finally:
        def check_sentinel():
            if sentinel is None:
                evidence['sentinel_not_ready'] = True
                return
            try:
                connection, peer = sentinel.accept()
            except socket.timeout:
                evidence['cni_connections'] = []
            except OSError:
                evidence['sentinel_not_ready'] = True
            else:
                connection.close()
                evidence['cni_connections'] = [str(peer)]
                raise AssertionError('Closed workflow connected to its CNI sentinel')
            finally:
                sentinel.close()
        def check_sources():
            evidence['source_hashes_after'] = source_hashes(args, spec)
            evidence['source_hashes_unchanged'] = evidence['source_hashes_before'] == evidence['source_hashes_after']
            require(evidence['source_hashes_unchanged'], 'Proof sources changed during execution')
        cleanup(evidence, [('close owned service', service.close),
                           ('check and close loopback sentinel', check_sentinel),
                           ('verify source fingerprints', check_sources)])
    require(evidence.get('cni_connections') == [], 'Sentinel must be observed without connections')
    require(service.report['cleanup_complete'], 'Owned native cleanup incomplete')
    evidence['passed'] = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('vendor', 'java', 'spec-dir', 'output'):
        parser.add_argument('--' + argument, required=True)
    args = parser.parse_args(argv)
    evidence = {'format': 'cbus-edlt-terminal-model-native-durability-v1', 'passed': False,
        'scope': 'one synthetic closed-model image database durability; not original template Apply/OK acceptance',
        'physical_devices_accessed': False, 'template_apply_executed': False,
        'metadata_provenance': 'synthetic caller fixtures', 'cache_freshness_verified': False,
        'database_metadata_created': False,
        'original_save_validation_verified': False, 'complete_parent_lifecycle_verified': False,
        'pp_save_attempted': False, 'pp_save_confirmed': False, 'pp_save_outcome_uncertain': False,
        'project_save_attempted': False, 'project_save_confirmed': False, 'project_save_outcome_uncertain': False,
        'fresh_pp_reload_attempted': False, 'fresh_pp_reload_verified': False, 'automatic_retries': 0}
    with Path(args.output).open('x', encoding='utf-8') as stream:
        try:
            run(args, evidence)
        except BaseException as error:
            evidence['error'] = error_record(error)
            raise
        finally:
            json.dump(evidence, stream, indent=2); stream.write('\n')
    print(json.dumps({'passed': True, 'output': args.output, 'parameters_compared_on_reload': 874,
        'crcs_compared_on_reload': 5, 'cni_connections': [], 'complete_parent_lifecycle_verified': False}))
    return 0


if __name__ == '__main__': sys.exit(main())
