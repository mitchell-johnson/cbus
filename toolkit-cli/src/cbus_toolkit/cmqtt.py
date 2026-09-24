"""Read physical eDLT labels through cmqttd's shared C-Gate/PCI service.

The READMEM/IDENTIFY commands are cmqttd extensions. No Windows process,
vendor schema, direct CNI connection, or EEPROM write is used by this reader.
"""
from __future__ import annotations

import hashlib
import json
import re
from .edlt import configuration_crc


def _object(client, command):
    response = client.command(command)
    if response.status != 200 or len(response.lines) != 2 or not response.lines[0].startswith('200-'):
        raise ValueError('Unexpected cmqttd response envelope')
    result = json.loads(response.lines[0][4:])
    if not isinstance(result, dict):
        raise ValueError('Expected a cmqttd JSON object')
    return result


def _bytes(client, address, command, **expected):
    value = _object(client, command)
    if value.get('source') != 'physical' or value.get('address') != address or any(value.get(k) != v for k, v in expected.items()):
        raise ValueError('cmqttd response is not the requested physical read')
    data = value.get('data_hex')
    if not isinstance(data, str) or len(data) % 2 or not re.fullmatch('[0-9a-fA-F]*', data):
        raise ValueError('Invalid memory data from cmqttd')
    return bytes.fromhex(data)


def read_memory(client, address, offset, length):
    if not re.fullmatch(r'//[A-Za-z0-9_-]+/[0-9]{1,3}/p/[0-9]{1,3}', address):
        raise ValueError('Use a fully qualified //PROJECT/NETWORK/p/UNIT address')
    if type(offset) is not int or type(length) is not int or not 0 <= offset <= 0xffffffff or not 1 <= length <= 65536 or offset + length > 0xffffffff:
        raise ValueError('Invalid physical memory range')
    result = bytearray()
    while len(result) < length:
        position, count = offset + len(result), min(256, length - len(result))
        part = _bytes(client, address, f'UNIT READMEM {address} {position} {count}', physical_address=position)
        if len(part) != count:
            raise ValueError('cmqttd returned an incomplete memory block')
        result.extend(part)
    return bytes(result)


def decode_observed_labels(value):
    """Assemble cmqttd's bounded SAL observations without claiming readback."""
    if not isinstance(value, dict) or value.get('format') != 'cmqttd-observed-dynamic-labels-v1':
        raise ValueError('Invalid cmqttd dynamic-label observation document')
    if value.get('source') != 'observed-sal-traffic' or value.get('complete') is not False or value.get('device_readback') is not False:
        raise ValueError('cmqttd dynamic-label provenance is missing or unsafe')
    observations = value.get('observations')
    capacity = value.get('capacity')
    if type(capacity) is not int or not 1 <= capacity <= 65536 or not isinstance(observations, list) or len(observations) > capacity:
        raise ValueError('Invalid cmqttd dynamic-label observation bounds')
    current, unicode_pending, icon_pending = {}, {}, {}
    languages, decoded, errors = {}, [], []
    previous = -1

    def target(application, payload, selected, action_index, variant):
        action = payload[action_index] if selected else None
        return application, payload[1], action, variant

    def commit(key, item):
        current[key] = item
        decoded.append(item)

    for row in observations:
        if not isinstance(row, dict) or set(row) != {'sequence', 'direction', 'source_unit', 'application', 'payload_hex'}:
            raise ValueError('Invalid dynamic-label observation row')
        sequence, direction = row['sequence'], row['direction']
        source_unit, application, payload_hex = row['source_unit'], row['application'], row['payload_hex']
        if type(sequence) is not int or sequence <= previous or direction not in ('received', 'sent-confirmed'):
            raise ValueError('Invalid dynamic-label observation sequence')
        previous = sequence
        if source_unit is not None and (type(source_unit) is not int or not 0 <= source_unit <= 255):
            raise ValueError('Invalid dynamic-label source unit')
        if type(application) is not int or application not in (*range(48, 96), 202, 203):
            raise ValueError('Invalid dynamic-label application')
        if not isinstance(payload_hex, str) or len(payload_hex) % 2 or not re.fullmatch('[0-9a-fA-F]+', payload_hex):
            raise ValueError('Invalid dynamic-label payload encoding')
        payload = bytes.fromhex(payload_hex)
        if not payload or (payload[0] & 0xe0) not in (0xa0, 0xc0) or (payload[0] & 0x1f) + 1 != len(payload):
            raise ValueError('Invalid dynamic-label payload length')
        common = {'application': application, 'sequence': sequence, 'direction': direction,
                  'source_unit': source_unit, 'delivery_confirmed': direction == 'sent-confirmed',
                  'device_readback': False, 'payload_hex': payload_hex.lower()}
        if payload[0] & 0xe0 == 0xc0:
            if application == 203 or len(payload) < 5:
                raise ValueError('Invalid Unicode dynamic-label payload')
            control, options = payload[2], payload[3]
            selected, variant = bool(options & 0x80), options & 3
            if control & 3 != (3 if selected else 2):
                raise ValueError('Invalid Unicode dynamic-label target')
            index = 4
            key_base = target(application, payload, selected, index, variant)
            index += int(selected)
            if index >= len(payload):
                raise ValueError('Truncated Unicode dynamic-label payload')
            language, data = payload[index], payload[index + 1:]
            key = (*key_base, language)
            phase, fragment = control & 0x0c, control >> 4
            if phase == 12:
                chunks, raw = [data], [payload_hex.lower()]
            elif phase == 0:
                unicode_pending[key] = {'next': (fragment + 1) & 15, 'chunks': [data],
                                        'raw': [payload_hex.lower()], 'common': common}
                continue
            else:
                pending = unicode_pending.get(key)
                if pending is None or pending['next'] != fragment:
                    errors.append({'sequence': sequence, 'error': 'unmatched Unicode label fragment'})
                    unicode_pending.pop(key, None)
                    continue
                pending['chunks'].append(data); pending['raw'].append(payload_hex.lower())
                pending['next'] = (fragment + 1) & 15
                if phase == 4:
                    continue
                if phase != 8:
                    errors.append({'sequence': sequence, 'error': 'invalid Unicode label phase'})
                    unicode_pending.pop(key, None)
                    continue
                chunks, raw = pending['chunks'], pending['raw']
                common = pending['common'] | common
                unicode_pending.pop(key, None)
            try:
                text = b''.join(chunks).decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                errors.append({'sequence': sequence, 'error': 'invalid assembled Unicode label'})
                continue
            commit(key, {**common, 'group': key_base[1], 'action_selector': key_base[2],
                         'variant': variant, 'language': language, 'kind': 'unicode-text',
                         'text': text, 'payloads_hex': raw})
            continue

        if len(payload) < 4:
            raise ValueError('Truncated standard dynamic-label payload')
        options, selected = payload[2], bool(payload[2] & 1)
        variant, mode, index = (options >> 5) & 3, options & 0x1e, 3
        key_base = target(application, payload, selected, index, variant)
        index += int(selected)
        transaction = key_base
        if mode == 4 and transaction in icon_pending:
            pending = icon_pending[transaction]
            if pending['phase'] == 'metadata':
                if len(payload[index:]) != 6:
                    errors.append({'sequence': sequence, 'error': 'invalid dynamic-icon metadata'})
                    icon_pending.pop(transaction, None); continue
                language, icon_high, icon_low, width, height, vertical = payload[index:]
                pending.update(phase='control', language=language, icon=(icon_high << 8) | icon_low,
                               width=width, height=height, vertical_offset=vertical)
            elif pending['phase'] == 'data':
                pending['data'].extend(payload[index:]); pending['phase'] = 'control'
            else:
                errors.append({'sequence': sequence, 'error': 'unexpected dynamic-icon data'})
                icon_pending.pop(transaction, None); continue
            pending['raw'].append(payload_hex.lower())
            continue
        if index >= len(payload):
            raise ValueError('Truncated standard dynamic-label payload')
        language, data = payload[index], payload[index + 1:]
        key = (*key_base, language)
        if mode == 8 and len(data) == 1 and data[0] in (0x20, 0x21, 0x22):
            control = data[0]
            if control == 0x20:
                icon_pending[transaction] = {'phase': 'metadata', 'data': bytearray(),
                                             'raw': [payload_hex.lower()], 'common': common}
            elif control == 0x21:
                pending = icon_pending.get(transaction)
                if pending is None or pending['phase'] != 'control':
                    errors.append({'sequence': sequence, 'error': 'unmatched dynamic-icon chunk control'})
                else:
                    pending['phase'] = 'data'; pending['raw'].append(payload_hex.lower())
            else:
                pending = icon_pending.pop(transaction, None)
                if pending is None or pending['phase'] != 'control' or 'language' not in pending:
                    errors.append({'sequence': sequence, 'error': 'unmatched dynamic-icon commit'}); continue
                expected = (pending['width'] * pending['height'] + 7) // 8
                if not 1 <= pending['width'] <= 240 or not 1 <= pending['height'] <= 60 or len(pending['data']) != expected:
                    errors.append({'sequence': sequence, 'error': 'invalid assembled dynamic icon'}); continue
                final_key = (*key_base, pending['language'])
                commit(final_key, {**pending['common'], **common, 'group': key_base[1],
                    'action_selector': key_base[2], 'variant': variant, 'language': pending['language'],
                    'kind': 'dynamic-icon', 'icon': pending['icon'], 'width': pending['width'],
                    'height': pending['height'], 'vertical_offset': pending['vertical_offset'],
                    'data_hex': bytes(pending['data']).hex(),
                    'payloads_hex': pending['raw'] + [payload_hex.lower()]})
            continue
        if mode == 0:
            text = None
            try:
                text = (b'' if data == b'\0' else data).decode('ascii', errors='strict')
                if any(ord(character) < 32 or ord(character) == 127 for character in text):
                    text = None
            except UnicodeDecodeError:
                pass
            item = {**common, 'group': key_base[1], 'action_selector': key_base[2],
                    'variant': variant, 'language': language, 'kind': 'standard',
                    'data_hex': data.hex(), 'text': text, 'payloads_hex': [payload_hex.lower()]}
            commit(key, item)
        elif mode == 2 and len(data) == 3 and data[0] == 1:
            commit(key, {**common, 'group': key_base[1], 'action_selector': key_base[2],
                         'variant': variant, 'language': language, 'kind': 'built-in-icon',
                         'icon': int.from_bytes(data[1:], 'big'), 'payloads_hex': [payload_hex.lower()]})
        elif mode == 6 and not data:
            languages[(application, key_base[1], key_base[2])] = {
                **common, 'group': key_base[1], 'action_selector': key_base[2], 'language': language}
        else:
            commit(key, {**common, 'group': key_base[1], 'action_selector': key_base[2],
                         'variant': variant, 'language': language, 'kind': 'raw',
                         'options': mode, 'data_hex': data.hex(),
                         'payloads_hex': [payload_hex.lower()]})
    entries = sorted(current.values(), key=lambda row: (
        row['application'], row['group'], -1 if row['action_selector'] is None else row['action_selector'],
        row['variant'], row['language']))
    return {'format': 'cbus-observed-dynamic-label-cache-v1', 'complete': False,
            'device_readback': False, 'reset_on_reconnect': value.get('reset_on_reconnect') is True,
            'observation_count': len(observations), 'entries': entries,
            'language_selections': sorted(languages.values(), key=lambda row: row['sequence']),
            'incomplete_transactions': len(unicode_pending) + len(icon_pending), 'errors': errors}


def decode_edlt_labels(memory):
    """Decode the evidenced KEYGL5 5.5.00 static-label/widget memory layout."""
    if not isinstance(memory, bytes) or len(memory) != 9216:
        raise ValueError('An eDLT image must contain exactly 9216 physical bytes')
    if memory[:2] != b'\x05\x01':
        raise ValueError('Unsupported eDLT configuration version')
    text_bytes = memory[0x1000:0x2000]
    expected = int.from_bytes(memory[8:10], 'big')
    raw_crc = configuration_crc(text_bytes[:4095])
    strings = []
    projected = bytearray()
    for index in range(64):
        record = text_bytes[index * 64:(index + 1) * 64]
        if b'\0' not in record:
            raise ValueError(f'Static string {index} has no terminator')
        content = record.split(b'\0', 1)[0]
        strings.append(content.decode('utf-8', errors='strict'))
        # Toolkit constructs a fresh zero-filled text image. Physical storage
        # may retain bytes after a shortened string's NUL terminator.
        projected.extend(content.ljust(64, b'\0'))
    projected_crc = configuration_crc(bytes(projected[:4095]))
    if expected not in (raw_crc, projected_crc):
        raise ValueError('eDLT static-text CRC mismatch; labels cannot be verified')
    def text(index):
        if index == 255:
            return None
        if not 0 <= index < 64:
            raise ValueError('Invalid eDLT static string reference')
        return strings[index]
    scenes = {}
    bucket = memory[0x2012:0x2012 + 232]
    for number in range(1, 9):
        pointer = int.from_bytes(memory[0x2000 + number * 2:0x2002 + number * 2], 'little')
        if pointer in (255, 65535):
            continue
        if pointer >= len(bucket):
            raise ValueError('Invalid eDLT scene pointer')
        if bucket[pointer] == 255:
            continue
        if pointer + 5 > len(bucket) or pointer + 5 + 3 * bucket[pointer + 1] > len(bucket):
            raise ValueError('Truncated eDLT scene record')
        scenes[number] = {'index': bucket[pointer + 4], 'text': text(bucket[pointer + 4])}
    nav = memory[0x100]
    if nav not in (0, 1):
        raise ValueError('Unsupported eDLT navigation layout')
    pairs = {2: (13, 14), 3: (10, 11), 4: (9, 10), 5: (17, 18),
             14: (11, 12), 15: (8, 9), 16: (9, 10)}
    widgets = []
    terminated = False
    for widget in range(1, 22):
        start = 0x120 + (widget - 1) * 32
        record = memory[start:start + 32]
        kind, control = record[:2]
        if kind not in (0, *range(2, 17), 255):
            raise ValueError(f'Unknown eDLT widget type {kind}')
        if widget >= 6 and kind == 255:
            terminated = True
        if kind in (0, 255):
            continue
        if widget >= 6 and terminated:
            raise ValueError('An active widget follows the end marker')
        label_type = (control >> 4) & 7
        item = {'widget': widget, 'widget_type': kind, 'standby': widget < 6,
                'page': 0 if widget < 6 else 1 if nav == 0 else 1 + (widget - 6) // 4,
                'position': widget if widget < 6 else widget - 5 if nav == 0 else 1 + (widget - 6) % 4,
                'visible': widget < 6 or nav == 1 or widget <= 10,
                'label_type': label_type, 'label': None, 'status_text': None, 'record_hex': record.hex()}
        if kind in pairs:
            label_offset, status_offset = pairs[kind]
            if label_type == 3:
                item.update(label_index=record[label_offset], label=text(record[label_offset]))
            if control & 15 == 5:
                item['status_text'] = text(record[status_offset])
        elif kind == 6:
            item['scene'] = record[6] + 1
            if label_type == 3:
                if item['scene'] not in scenes:
                    raise ValueError('Scene widget refers to an absent scene')
                item.update(label_index=scenes[item['scene']]['index'], label=scenes[item['scene']]['text'])
        if kind == 2:
            item['group'] = record[6]
            item['application'] = memory[17 if control & 128 else 16]
        if label_type in (1, 2):
            item['label_source'] = 'dynamic-cache-not-read'
        widgets.append(item)
    return {'page_mode': 'single' if nav == 0 else 'multiple', 'widgets': widgets,
            'static_strings': [{'index': i, 'text': value} for i, value in enumerate(strings)],
            'scenes': scenes, 'static_text_crc_verified': True, 'dynamic_labels_verified': False,
            'raw_static_text_crc_verified': expected == raw_crc,
            'static_text_crc_method': 'physical-bytes' if expected == raw_crc else 'toolkit-zero-padded-strings',
            'memory_sha256': hashlib.sha256(memory).hexdigest()}


def edlt_labels(client, address):
    # Validate before sending any operation.
    if not re.fullmatch(r'//[A-Za-z0-9_-]+/[0-9]{1,3}/p/[0-9]{1,3}', address):
        raise ValueError('Use a fully qualified //PROJECT/NETWORK/p/UNIT address')
    metadata = _object(client, f'CMQTT UNIT {address}')
    unit_type = _bytes(client, address, f'UNIT IDENTIFY {address} 1', attribute=1).decode('ascii').strip(' \0')
    firmware = _bytes(client, address, f'UNIT IDENTIFY {address} 2', attribute=2).decode('ascii').strip(' \0')
    if unit_type != 'KEYGL5' or not re.fullmatch(r'0?5\.0?5\.0{1,2}', firmware):
        raise ValueError(f'Unsupported physical eDLT identity: {unit_type} {firmware}')
    before = read_memory(client, address, 0, 16)
    memory = read_memory(client, address, 0, 9216)
    after = read_memory(client, address, 0, 16)
    if before != memory[:16] or before != after:
        raise ValueError('eDLT configuration changed during the read; retry the snapshot')
    observed = decode_observed_labels(_object(client, f'CMQTT LABELS {address}'))
    return {'address': address, 'name': metadata.get('name'), 'unit_type': unit_type,
            'firmware': firmware, 'source': 'physical-via-cmqttd', 'configuration_header_stable': True,
            **decode_edlt_labels(memory), 'observed_dynamic_labels': observed,
            'dynamic_labels_observed': bool(observed['entries'])}
