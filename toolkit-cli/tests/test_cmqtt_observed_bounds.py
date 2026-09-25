"""Bounds, identity, and partial/corrupt hardening for observed dynamic labels.

TDD pins for issue #12 Phase 1: text, Unicode, icons, dynamic bitmaps,
languages, application/group/variant identity, bounds, and partial/corrupt
records must never be misreported as verified device readback.
"""
import pytest

from cbus_toolkit.cmqtt import decode_observed_labels
from cbus_toolkit.labels import encode_dynamic_icon, encode_label, encode_unicode_label


def doc(observations, **overrides):
    value = {
        "format": "cmqttd-observed-dynamic-labels-v1",
        "source": "observed-sal-traffic",
        "complete": False,
        "device_readback": False,
        "reset_on_reconnect": True,
        "capacity": 4096,
        "observations": observations,
    }
    value.update(overrides)
    return value


def row(sequence, application, payload, direction="sent-confirmed", source_unit=None):
    return {
        "sequence": sequence,
        "direction": direction,
        "source_unit": source_unit,
        "application": application,
        "payload_hex": payload.hex(),
    }


def test_provenance_variants_reject_unsafe_claims():
    good = doc([])
    assert decode_observed_labels(good)["device_readback"] is False
    for bad in (
        doc([], format="other"),
        doc([], source="database"),
        doc([], complete=True),
        doc([], device_readback=True),
        {"not": "a document"},
    ):
        with pytest.raises(ValueError):
            decode_observed_labels(bad)


def test_network_provenance_trio_is_carried_and_old_v1_is_compatible():
    legacy = decode_observed_labels(doc([]))
    assert legacy['observation_scope'] == 'network'
    assert legacy['recipient_verified'] is False
    assert legacy['requested_address'] is None
    assert legacy['provenance_explicit'] is False

    current = decode_observed_labels(doc([], observation_scope='network',
                                         recipient_verified=False,
                                         requested_address='//TEST/254'))
    assert current['observation_scope'] == 'network'
    assert current['recipient_verified'] is False
    assert current['requested_address'] == '//TEST/254'
    assert current['provenance_explicit'] is True


@pytest.mark.parametrize('overrides', [
    {'observation_scope': 'network'},
    {'recipient_verified': False},
    {'requested_address': '//TEST/254'},
    {'observation_scope': 'network', 'recipient_verified': False},
    {'observation_scope': 'network', 'requested_address': '//TEST/254'},
    {'recipient_verified': False, 'requested_address': '//TEST/254'},
    {'observation_scope': 'unit', 'recipient_verified': False,
     'requested_address': '//TEST/254'},
    {'observation_scope': 'network', 'recipient_verified': True,
     'requested_address': '//TEST/254'},
    {'observation_scope': 'network', 'recipient_verified': False,
     'requested_address': 254},
])
def test_partial_or_unsafe_network_provenance_rejects(overrides):
    with pytest.raises(ValueError):
        decode_observed_labels(doc([], **overrides))


def test_reset_on_reconnect_missing_defaults_false_but_accepted():
    result = doc([])
    del result["reset_on_reconnect"]
    assert decode_observed_labels(result)["reset_on_reconnect"] is False
    assert decode_observed_labels(doc([], reset_on_reconnect=True))["reset_on_reconnect"] is True
    assert decode_observed_labels(doc([], reset_on_reconnect=False))["reset_on_reconnect"] is False
    assert decode_observed_labels(doc([], reset_on_reconnect=1))["reset_on_reconnect"] is False


@pytest.mark.parametrize("capacity", [0, -1, 70000, "4096", None, True, False])
def test_capacity_bounds_reject(capacity):
    with pytest.raises(ValueError):
        decode_observed_labels(doc([], capacity=capacity))


@pytest.mark.parametrize("capacity", [1, 4096, 65536])
def test_capacity_boundaries_accept(capacity):
    assert decode_observed_labels(doc([], capacity=capacity))["observation_count"] == 0


def test_observations_longer_than_capacity_reject():
    payload = encode_label(1, 0, 0, b"X")
    rows = [row(i, 56, payload) for i in range(3)]
    with pytest.raises(ValueError):
        decode_observed_labels(doc(rows, capacity=2))


@pytest.mark.parametrize("direction", ["sent", "received-early", "CONFIRMED", "", None])
def test_direction_must_be_received_or_sent_confirmed(direction):
    payload = encode_label(1, 0, 0, b"X")
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, 56, payload, direction=direction)]))


@pytest.mark.parametrize("direction", ["received", "sent-confirmed"])
def test_direction_whitelist_accepts_both_directions(direction):
    payload = encode_label(1, 0, 0, b"X")
    result = decode_observed_labels(doc([row(0, 56, payload, direction=direction)]))
    assert len(result["entries"]) == 1
    assert result["entries"][0]["direction"] == direction
    assert result["entries"][0]["delivery_confirmed"] == (direction == "sent-confirmed")


def test_sequence_must_strictly_increase():
    payload = encode_label(1, 0, 0, b"X")
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, 56, payload), row(0, 56, payload)]))
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(1, 56, payload), row(0, 56, payload)]))


@pytest.mark.parametrize("sequence", ["0", 0.0, True, None])
def test_sequence_type_rejects(sequence):
    payload = encode_label(1, 0, 0, b"X")
    bad = row(0, 56, payload)
    bad["sequence"] = sequence
    with pytest.raises(ValueError):
        decode_observed_labels(doc([bad]))


def test_gapped_but_increasing_sequence_accepts():
    payload = encode_label(1, 0, 0, b"X")
    result = decode_observed_labels(doc([row(0, 56, payload), row(41, 56, payload)]))
    assert len(result["entries"]) == 1  # same key: later observation wins


@pytest.mark.parametrize("source_unit", [-1, 256, "5", 1.5, True])
def test_source_unit_bounds_reject(source_unit):
    payload = encode_label(1, 0, 0, b"X")
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, 56, payload, source_unit=source_unit)]))


@pytest.mark.parametrize("source_unit", [0, 255])
def test_source_unit_boundaries_accept(source_unit):
    payload = encode_label(1, 0, 0, b"X")
    result = decode_observed_labels(doc([row(0, 56, payload, source_unit=source_unit)]))
    assert result["entries"][0]["source_unit"] == source_unit


@pytest.mark.parametrize("application", [0, 47, 96, 200, 201, 204, 300, "56", None])
def test_application_identity_bounds_reject(application):
    payload = encode_label(1, 0, 0, b"X")
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, application, payload)]))


@pytest.mark.parametrize("application", [48, 95, 202, 203])
def test_application_boundaries_accept(application):
    payload = encode_label(1, 0, 0, b"Ok")
    result = decode_observed_labels(doc([row(0, application, payload)]))
    assert len(result["entries"]) == 1
    assert result["entries"][0]["application"] == application


@pytest.mark.parametrize(
    "payload_hex", ["0", "zz", "", None, 123],
)
def test_payload_hex_encoding_reject(payload_hex):
    bad = row(0, 56, encode_label(1, 0, 0, b"X"))
    bad["payload_hex"] = payload_hex
    with pytest.raises(ValueError):
        decode_observed_labels(doc([bad]))


def test_payload_length_mismatch_rejects():
    payload = bytearray(encode_label(1, 0, 0, b"Hi"))
    payload[0] ^= 0x01  # corrupt length nibble so opcode length != wire length
    assert (payload[0] & 0x1F) + 1 != len(payload)
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, 56, bytes(payload))]))


def test_unicode_on_enable_rejects_without_claiming_readback():
    # 0xC0 family on application 203 must fail closed, never decode.
    payload = encode_unicode_label(1, 0, "hi".encode(), sequence=3)[0]
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, 203, payload)]))


def test_truncated_unicode_and_standard_reject():
    # Length-correct wire payloads that end before the mandatory fields:
    # 0xC3 claims 4 bytes (unicode needs >= 5), 0xA2 claims 3 (standard >= 4).
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, 56, bytes.fromhex("c301e203"))]))
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, 56, bytes.fromhex("a20102"))]))
    # A bare single-byte opcode is valid hex but truncated all the same.
    with pytest.raises(ValueError):
        decode_observed_labels(doc([row(0, 56, bytes.fromhex("a0"))]))


def test_unmatched_unicode_fragment_reports_error_not_entry():
    frags = encode_unicode_label(8, 2, b"b" * 20, sequence=4)
    assert len(frags) == 2
    # Drop the first fragment: the closer has no pending start.
    result = decode_observed_labels(doc([row(0, 202, frags[1])]))
    assert result["entries"] == []
    assert result["incomplete_transactions"] == 0
    assert len(result["errors"]) == 1
    assert "unmatched" in result["errors"][0]["error"]
    assert result["device_readback"] is False


def test_restarted_unicode_transaction_drops_earlier_partial():
    # CURRENT-CODE-ONLY pin (no native citation yet): a second start fragment
    # for the same key supersedes the first partial transaction — no entry is
    # produced and exactly one incomplete remains. TODO: confirm against
    # native C-Gate whether overwrite (vs error/drop) is the true behavior;
    # see issue #12 physical dynamic-label cache reads.
    # NOTE: the decoder's `phase != 8` error branch is unreachable through the
    # opcode mask (phase can only be 0/4/8/12; 0 and 12 are handled earlier),
    # so it stays as defensive code and is not pinned here.
    frags = encode_unicode_label(8, 2, b"c" * 20, sequence=6)
    first, last = frags[0], bytearray(frags[1])
    last[2] = last[2] & 0xF3  # closing phase 8 -> second start, same fragment nibble
    result = decode_observed_labels(doc([row(0, 202, first), row(1, 202, bytes(last))]))
    assert result["entries"] == []
    assert result["incomplete_transactions"] == 1
    assert result["device_readback"] is False


def test_unmatched_dynamic_icon_chunk_and_commit_report_errors():
    start = encode_label(3, 0, 8, b"\x20")
    commit = encode_label(3, 0, 8, b"\x22")
    # Chunk-control with no open icon transaction.
    chunk_ctl = encode_label(3, 0, 8, b"\x21")
    result = decode_observed_labels(doc([row(0, 56, chunk_ctl)]))
    assert result["entries"] == []
    assert len(result["errors"]) == 1
    assert "chunk" in result["errors"][0]["error"]
    # Commit with no open transaction.
    result = decode_observed_labels(doc([row(0, 56, commit)]))
    assert len(result["errors"]) == 1
    assert "commit" in result["errors"][0]["error"]
    # Start alone stays pending as an incomplete transaction, never an entry.
    result = decode_observed_labels(doc([row(0, 56, start)]))
    assert result["entries"] == []
    assert result["incomplete_transactions"] == 1


def test_invalid_dynamic_icon_dimensions_report_error():
    tx = encode_dynamic_icon(3, 7, 9, 8, 7, b"\x01\x02\x04\x08\x10\x20\x40")
    tampered = [bytearray(p) for p in tx]
    # Metadata payload layout: opcode, group, options, language, iconHi, iconLo,
    # width, height, vertical. Set width to 0 (outside 1..240 native bounds).
    tampered[1][6] = 0
    tampered = [bytes(p) for p in tampered]
    result = decode_observed_labels(
        doc([row(i, 56, p) for i, p in enumerate(tampered)])
    )
    assert not [e for e in result["entries"] if e["kind"] == "dynamic-icon"]
    assert len(result["errors"]) == 1
    assert "icon" in result["errors"][0]["error"]
    assert result["device_readback"] is False


def test_mode6_empty_data_selects_language_and_data_falls_back_to_raw():
    # Empty data with options mode 6 records a language selection, not an entry.
    lang = encode_label(2, 5, 6, b"")
    result = decode_observed_labels(doc([row(0, 56, lang)]))
    assert result["entries"] == []
    assert len(result["language_selections"]) == 1
    assert result["language_selections"][0]["language"] == 5
    # Non-empty data with mode 6 has no language meaning: kept as raw,
    # never verified.
    raw = encode_label(2, 5, 6, b"\x09\x08")
    result = decode_observed_labels(doc([row(0, 56, raw)]))
    assert len(result["entries"]) == 1
    assert result["entries"][0]["kind"] == "raw"
    assert result["entries"][0]["device_readback"] is False


def test_identity_fields_preserved_and_never_verified():
    std = encode_label(5, 2, 0, b"Id", action_selector=7, variant=3)
    uni = encode_unicode_label(6, 1, "q".encode(), action_selector=4, variant=2, sequence=9)[0]
    result = decode_observed_labels(doc([row(0, 56, std), row(1, 202, uni)]))
    by_group = {item["group"]: item for item in result["entries"]}
    assert by_group[5]["application"] == 56
    assert by_group[5]["action_selector"] == 7
    assert by_group[5]["variant"] == 3
    assert by_group[5]["language"] == 2
    assert by_group[6]["action_selector"] == 4
    assert by_group[6]["variant"] == 2
    assert all(item["device_readback"] is False for item in result["entries"])
    assert result["complete"] is False
    assert result["format"] == "cbus-observed-dynamic-label-cache-v1"
