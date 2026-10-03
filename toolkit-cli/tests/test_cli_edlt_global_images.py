"""Offline automatic source and fail-before-connect CLI boundaries."""
from contextlib import redirect_stderr, redirect_stdout
import io
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cbus_toolkit import cli
from tests.test_edlt_global_programming import fixture

VECTOR = Path(__file__).resolve().parents[1] / 'research/fixtures/edlt-global-image-vectors.json'


def invoke(argv, expected=0):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = cli.main(list(map(str, argv)))
    assert status == expected, (status, out.getvalue(), err.getvalue())
    return json.loads(out.getvalue() or err.getvalue())


def files(tmp_path):
    vectors = json.loads(VECTOR.read_text())
    source = vectors['fixture']
    xml, images = tmp_path / 'source.xml', tmp_path / 'images.json'
    xml.write_text(source['project_xml'])
    images.write_bytes(source['project_images_raw'].encode())
    argv = ['edlt', '--spec-dir', tmp_path, 'global-plan',
            '--project-xml', xml, '--unit', source['source_unit'],
            '--project-images-export', images,
            '--project-images-sha256', source['project_images_sha256']]
    return vectors, source, argv, images


@pytest.mark.parametrize('mask', range(16))
def test_offline_automatic_source_all_masks_match_independent_literals(mask, tmp_path):
    vectors, source, argv, _images = files(tmp_path)
    case = vectors['masks'][mask]
    flags = [part for category in case['categories'] for part in ('--category', category)]
    with patch('cbus_toolkit.unitspec.UnitSpecStore.load', return_value=fixture()), \
            patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Offline cannot connect')):
        result = invoke([*argv, *flags])
    assert [(row['parameter'], ' '.join(hex(v) for v in row['value']))
            for row in result['ordered_payload']] == [tuple(row) for row in case['ordered_payload']]
    context = result['source']['image_context']
    assert context['source_unit'] == source['source_unit']
    assert context['source_language'] == vectors['expected_source']['source_language']
    assert context['label_transfer_performed'] is False
    assert context['image_upload_performed'] is False


@pytest.mark.parametrize('fault', ('missing-source', 'source-target', 'duplicate-target',
                                   'different-project', 'missing-image-hash', 'bad-image-hash',
                                   'foreign-image-project', 'factory', 'repeated-category'))
def test_native_automatic_invalid_input_refuses_before_connection(fault, tmp_path):
    _vectors, source, _argv, images = files(tmp_path)
    destination = source['targets'][0]['path']
    argv = ['cgate', 'edlt-global', '--spec-dir', tmp_path, '--auto-metadata',
            '--source-database', source['source_unit'], '--destination', destination,
            '--exclusive-project', '--project-images-export', images,
            '--project-images-sha256', source['project_images_sha256']]
    if fault == 'missing-source':
        index = argv.index('--source-database'); del argv[index:index + 2]
    elif fault == 'source-target':
        argv[argv.index('--destination') + 1] = source['source_unit']
    elif fault == 'duplicate-target':
        argv.extend(['--destination', destination])
    elif fault == 'different-project':
        argv[argv.index('--destination') + 1] = '//OTHER/254/p/21'
    elif fault == 'missing-image-hash':
        index = argv.index('--project-images-sha256'); del argv[index:index + 2]
    elif fault == 'bad-image-hash':
        argv[argv.index('--project-images-sha256') + 1] = '0' * 64
    elif fault == 'foreign-image-project':
        images.write_text(images.read_text().replace('IMGLOBAL', 'OTHER'))
        argv[argv.index('--project-images-sha256') + 1] = hashlib.sha256(images.read_bytes()).hexdigest()
    elif fault == 'factory':
        argv.extend(['--factory-context', tmp_path / 'not-read.json'])
    else:
        argv.extend(['--category', 'general', '--category', 'general'])
    with patch('cbus_toolkit.unitspec.UnitSpecStore.load', return_value=fixture()), \
            patch('cbus_toolkit.cgate.CGateClient', side_effect=AssertionError('Invalid cannot connect')) as connect:
        result = invoke(argv, 1)
    assert result['error']
    connect.assert_not_called()


def test_supplied_file_and_parameter_order_must_equal_project_source(tmp_path):
    _vectors, source, argv, _images = files(tmp_path)
    pp = tmp_path / 'pp.json'; pp.write_text(json.dumps(source['source_pp']))
    order = tmp_path / 'order.json'; order.write_text(json.dumps(source['parameter_order']))
    with patch('cbus_toolkit.unitspec.UnitSpecStore.load', return_value=fixture()):
        invoke([*argv[:4], pp, *argv[4:], '--parameter-order', order])
        wrong = dict(source['source_pp']); wrong['LongPressTime'] = [199]
        pp.write_text(json.dumps(wrong))
        assert 'differs' in invoke([*argv[:4], pp, *argv[4:]], 1)['error']
        order.write_text(json.dumps(list(reversed(source['parameter_order']))))
        assert 'reorder' in invoke([*argv, '--parameter-order', order], 1)['error']
