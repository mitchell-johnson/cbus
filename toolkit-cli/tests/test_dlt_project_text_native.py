"""Retained original-source/native text acceptance and opt-in fresh replay."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / 'research/fixtures/classic-dlt-project-text-native.json'
SCRIPT = ROOT / 'research/dlt_project_text_original.py'


def test_retained_native_text_receipt_and_source_binding():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt['source_sha256'] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert receipt['original']['exe_sha256'] == '9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab'
    assert receipt['original']['network_language_identity_field'] == 'ID'
    assert receipt['original']['literal_fields_verified'] == ['TagsDLT', 'TagDLT', 'LanguageID', 'FlavourID', 'TagType', 'TagValue']
    assert receipt['oracle']['jar_sha256'] == '3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630'
    for field in ('owned_loopback_listeners', 'cleanup_complete', 'work_removed', 'process_exit_confirmed'):
        assert receipt['oracle'][field] is True
    assert receipt['oracle']['physical_endpoint'] is False
    assert [case['kind'] for case in receipt['cases']] == ['Group', 'Level']
    for case in receipt['cases']:
        assert case['set_status'] == 301 and case['label_count'] == 6
        assert case['language_ids'] == [0, 1, 255] and case['variants'] == [1, 2, 3, 4]
        assert len(case['text_cases']) == 6
        for field in ('new_tag_oids_allocated', 'existing_tag_oids_retained', 'other_variants_preserved',
                      'language_definitions_preserved', 'save_close_load_verified'):
            assert case[field] is True
    assert receipt['cases'][1]['action_address_and_value_preserved'] is True
    assert receipt['labels_transferred'] is False and receipt['display_verified'] is False
    assert receipt['original']['original_gui_executed'] is False


@pytest.mark.skipif(os.environ.get('CBUS_DLT_TEXT_NATIVE') != '1', reason='Set CBUS_DLT_TEXT_NATIVE=1 and explicit vendor/Java paths for owned loopback replay')
def test_fresh_native_text_save_reload():
    sys.path.insert(0, str(ROOT / 'research'))
    try:
        from dlt_project_text_original import run
        receipt = run(Path(os.environ['CBUS_DLT_VENDOR_ROOT']), Path(os.environ['CBUS_CGATE_JAVA']))
    finally:
        sys.path.pop(0)
    assert receipt == json.loads(RECEIPT.read_text())
