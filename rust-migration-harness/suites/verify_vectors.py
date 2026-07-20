#!/usr/bin/env python3
"""Verifies the committed golden vectors against the *Python* working tree.

This is the harness's own sanity check: every vector in vectors/*.jsonl is
re-executed with the current Python cbus package and must reproduce the
recorded expectations bit-for-bit. Run with the repo venv:

    .venv/bin/python rust-migration-harness/suites/verify_vectors.py

Exits 0 if every vector passes, 1 otherwise, printing a per-file summary.
(The Rust equivalent of this program is rust/target/debug/cbus-vector-check;
see README.md for the contract.)
"""
import asyncio
import json
import os
import sys

HARNESS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(HARNESS_DIR)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(HARNESS_DIR, 'lib'))

import warnings
warnings.simplefilter('ignore')

from cbus.common import cbus_checksum, duration_to_ramp_rate, \
    ramp_rate_to_duration
from cbus.protocol.packet import decode_packet
from cbus.daemon.topics import (
    ga_string, set_topic, state_topic, conf_topic,
    bin_sensor_state_topic, bin_sensor_conf_topic)
from cbus.daemon.mqtt_gateway import MqttClient, get_topic_group_address

from pyjson import packet_to_json, packet_from_json

VEC_DIR = os.path.join(HARNESS_DIR, 'vectors')


def check_decode(v):
    wire = bytes.fromhex(v['wire_hex'])
    p, consumed = decode_packet(wire, checksum=v['checksum'],
                                strict=v['strict'], from_pci=v['from_pci'])
    if consumed != v['expect_consumed']:
        return f'consumed {consumed} != {v["expect_consumed"]}'
    got = packet_to_json(p)
    if got != v['expect_packet']:
        return f'packet {got!r} != {v["expect_packet"]!r}'
    if v.get('expect_reencode') is not None:
        try:
            re = p.encode_packet().decode('latin-1')
        except Exception as e:
            return f'reencode raised {e!r}'
        if re != v['expect_reencode']:
            return f'reencode {re!r} != {v["expect_reencode"]!r}'
    return None


def check_encode(v):
    obj = packet_from_json(v['packet'])
    got = obj.encode().hex()
    if got != v['expect_encode_hex']:
        return f'encode {got} != {v["expect_encode_hex"]}'
    if 'expect_encode_packet' in v:
        got2 = obj.encode_packet().decode('latin-1')
        if got2 != v['expect_encode_packet']:
            return f'encode_packet {got2!r} != {v["expect_encode_packet"]!r}'
    return None


def check_checksum(v):
    got = cbus_checksum(bytes.fromhex(v['data_hex']))
    if got != v['expect_checksum']:
        return f'checksum {got} != {v["expect_checksum"]}'
    return None


def check_ramp(v):
    if v['kind'] == 'duration_to_rate':
        got = int(duration_to_ramp_rate(v['in']))
    else:
        got = ramp_rate_to_duration(v['in'])
    if got != v['expect']:
        return f'{v["kind"]}({v["in"]}) = {got} != {v["expect"]}'
    return None


def check_topic(v):
    if v['kind'] == 'format':
        ga, app = v['group_addr'], v['app_addr']
        checks = [
            ('expect_ga_string_padded', ga_string(ga, app, True)),
            ('expect_ga_string_unpadded', ga_string(ga, app, False)),
            ('expect_set_topic', set_topic(ga, app)),
            ('expect_state_topic', state_topic(ga, app)),
            ('expect_conf_topic', conf_topic(ga, app)),
            ('expect_bin_sensor_state_topic',
             bin_sensor_state_topic(ga, app)),
            ('expect_bin_sensor_conf_topic',
             bin_sensor_conf_topic(ga, app)),
        ]
        for key, got in checks:
            if got != v[key]:
                return f'{key}: {got!r} != {v[key]!r}'
        return None
    # parse
    try:
        g, a = get_topic_group_address(v['topic'])
    except (ValueError, KeyError):
        return None if v.get('expect_error') else 'unexpected parse error'
    if v.get('expect_error'):
        return f'expected error, parsed ({g}, {a})'
    if g != v['expect_group'] or int(a) != v['expect_app']:
        return f'parsed ({g},{int(a)}) != ' \
               f'({v["expect_group"]},{v["expect_app"]})'
    return None


class _RecordingClient:
    def __init__(self):
        self.published = []
        self.subscribed = []

    async def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))

    async def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))


async def _run_publish_light(ga, app, labels):
    rec = _RecordingClient()
    mc = MqttClient.__new__(MqttClient)
    mc._client = rec
    mc.groupDB = {}
    mc.publish_light(ga, app, labels)
    await asyncio.sleep(0.02)
    return rec


async def _run_publish_all(labels):
    rec = _RecordingClient()
    mc = MqttClient.__new__(MqttClient)
    mc._client = rec
    mc.groupDB = {}
    mc.publish_all_lights(labels)
    await asyncio.sleep(0.02)
    return rec


def check_ha(v, loop):
    if v.get('meta'):
        rec = loop.run_until_complete(_run_publish_all({}))
        (t, payload, qos, retain) = rec.published[0]
        if t != v['expect_topic']:
            return f'topic {t!r} != {v["expect_topic"]!r}'
        if json.loads(payload) != v['expect_config']:
            return 'meta config mismatch'
        if qos != v['expect_qos'] or retain != v['expect_retain']:
            return f'qos/retain {qos}/{retain}'
        return None
    labels = None
    if v['labels']:
        labels = {int(k): (name, {int(g): n for g, n in groups.items()})
                  for k, (name, groups) in v['labels'].items()}
    rec = loop.run_until_complete(
        _run_publish_light(v['group_addr'], v['app_addr'], labels))
    pubs = {t: (json.loads(p), qos, retain)
            for (t, p, qos, retain) in rec.published}
    if rec.subscribed[0][0] != v['expect_subscribe']:
        return f'subscribe {rec.subscribed[0]!r}'
    if rec.subscribed[0][1] != v['expect_subscribe_qos']:
        return f'subscribe qos {rec.subscribed[0][1]}'
    for tk, ck in (('expect_light_config_topic', 'expect_light_config'),
                   ('expect_sensor_config_topic', 'expect_sensor_config')):
        topic = v[tk]
        if topic not in pubs:
            return f'no publish on {topic}'
        cfg, qos, retain = pubs[topic]
        if cfg != v[ck]:
            return f'config mismatch on {topic}'
        if qos != v['expect_qos'] or retain != v['expect_retain']:
            return f'qos/retain on {topic}: {qos}/{retain}'
    return None


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    files = [
        ('decode_from_pci.jsonl', check_decode),
        ('decode_to_pci.jsonl', check_decode),
        ('encode.jsonl', check_encode),
        ('checksum.jsonl', check_checksum),
        ('ramp_rates.jsonl', check_ramp),
        ('mqtt_topics.jsonl', check_topic),
        ('ha_discovery.jsonl', lambda v: check_ha(v, loop)),
    ]
    total = passed = 0
    any_fail = False
    for fname, checker in files:
        path = os.path.join(VEC_DIR, fname)
        n = ok = 0
        failures = []
        with open(path) as f:
            for line in f:
                v = json.loads(line)
                n += 1
                err = checker(v)
                if err is None:
                    ok += 1
                else:
                    failures.append((v['id'], err))
        total += n
        passed += ok
        status = 'PASS' if ok == n else 'FAIL'
        print(f'  {fname}: {ok}/{n} {status}')
        for vid, err in failures[:5]:
            print(f'    {vid}: {err}')
            any_fail = True
        if len(failures) > 5:
            print(f'    ... and {len(failures) - 5} more')
    print(f'selfcheck-vectors: {passed}/{total} PASS')
    sys.exit(1 if (any_fail or passed != total) else 0)


if __name__ == '__main__':
    main()
