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
    return {'address': address, 'name': metadata.get('name'), 'unit_type': unit_type,
            'firmware': firmware, 'source': 'physical-via-cmqttd', 'configuration_header_stable': True,
            **decode_edlt_labels(memory)}
