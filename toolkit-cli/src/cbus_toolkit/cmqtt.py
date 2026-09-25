"""Read physical eDLT labels through cmqttd's shared C-Gate/PCI service.

The READMEM/IDENTIFY commands are cmqttd extensions. No Windows process,
vendor schema, direct CNI connection, or EEPROM write is used by this reader.
"""
from __future__ import annotations

import hashlib
import json
import re
from .edlt import configuration_crc


_UNIT_ADDRESS = re.compile(r'//([A-Za-z0-9_]{1,8})/([0-9]{1,3})/p/([0-9]{1,3})')
_NETWORK_ADDRESS = re.compile(r'//([A-Za-z0-9_]{1,8})/([0-9]{1,3})')
_EDLT_FIRMWARE = re.compile(r'0?5\.0?5\.0{1,2}')


def _unit(address):
    match = _UNIT_ADDRESS.fullmatch(address) if isinstance(address, str) else None
    if match is None:
        raise ValueError('Use a fully qualified //PROJECT/NETWORK/p/UNIT address')
    network, unit = int(match[2]), int(match[3])
    if network > 255 or unit > 255:
        raise ValueError('C-Bus network and unit addresses must be in 0..255')
    return f'//{match[1]}/{network}/p/{unit}'


def _network_for_unit(address):
    return _unit(address).rsplit('/p/', 1)[0]


def _network(address):
    match = _NETWORK_ADDRESS.fullmatch(address) if isinstance(address, str) else None
    if match is None:
        raise ValueError('Use a fully qualified //PROJECT/NETWORK address')
    network = int(match[2])
    if network > 255:
        raise ValueError('C-Bus network address must be in 0..255')
    return f'//{match[1]}/{network}'


def _supported_edlt(unit_type, firmware):
    return unit_type == 'KEYGL5' and isinstance(firmware, str) and _EDLT_FIRMWARE.fullmatch(firmware) is not None


def _physical_serial(client, address):
    """Read and decode the exact serial carried by physical IDENTIFY4."""
    data = _bytes(client, address, f'UNIT IDENTIFY {address} 4', attribute=4)
    if len(data) != 12:
        raise ValueError('Physical IDENTIFY4 must contain exactly twelve bytes')
    packed = int.from_bytes(data[5:9], 'big')
    from .serials import parse_native_serial
    serial = parse_native_serial(f'{packed >> 12}.{packed & 4095}')
    if not serial.known:
        raise ValueError('Physical IDENTIFY4 returned an unknown serial')
    return serial.canonical, data.hex()


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
    address = _unit(address)
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
    provenance_fields = ('observation_scope', 'recipient_verified', 'requested_address')
    provenance_present = tuple(field in value for field in provenance_fields)
    if any(provenance_present) and not all(provenance_present):
        raise ValueError('cmqttd dynamic-label network provenance is incomplete')
    provenance_explicit = all(provenance_present)
    if provenance_explicit:
        if (value['observation_scope'] != 'network' or value['recipient_verified'] is not False
                or not isinstance(value['requested_address'], str)):
            raise ValueError('cmqttd dynamic-label network provenance is unsafe')
        requested_address = value['requested_address']
    else:
        # Pre-provenance v1 fixtures remain decodable, but no requested address
        # can be inferred from the observed SAL traffic itself.
        requested_address = None
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
            'device_readback': False, 'observation_scope': 'network',
            'recipient_verified': False, 'requested_address': requested_address,
            'provenance_explicit': provenance_explicit,
            'reset_on_reconnect': value.get('reset_on_reconnect') is True,
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
    uses = {index: [] for index in range(64)}
    special_uses = {64: [], 255: []}

    def reference(index, origin, *, measurement_empty=False):
        if index == 64 and measurement_empty:
            special_uses[64].append(origin)
            return ''
        if index == 255:
            special_uses[255].append(origin)
            return None
        if not 0 <= index < 64:
            raise ValueError('Invalid eDLT static string reference')
        uses[index].append(origin)
        return strings[index]

    scenes = {}
    bucket = memory[0x2012:0x2012 + 232]
    for number in range(1, 9):
        pointer = int.from_bytes(memory[0x2000 + number * 2:0x2002 + number * 2], 'little')
        if pointer in (255, 65535):
            special_uses[255].append(f'Scene{number}NameIndex')
            continue
        if pointer >= len(bucket):
            raise ValueError('Invalid eDLT scene pointer')
        if bucket[pointer] == 255:
            special_uses[255].append(f'Scene{number}NameIndex')
            continue
        if pointer + 5 > len(bucket) or pointer + 5 + 3 * bucket[pointer + 1] > len(bucket):
            raise ValueError('Truncated eDLT scene record')
        name_index = bucket[pointer + 4]
        scenes[number] = {'index': name_index,
                          'text': reference(name_index, f'Scene{number}NameIndex')}
    nav = memory[0x100]
    if nav not in (0, 1):
        raise ValueError('Unsupported eDLT navigation layout')
    nav_variant = memory[0x101] & 15
    page_names = []
    if nav_variant == 6:
        for page in range(1, 5):
            index = memory[0x104 + page]
            page_names.append({'page': page, 'index': index,
                               'text': reference(index, f'PageNameIndex{page}')})
    pairs = {2: (13, 14), 3: (10, 11), 4: (9, 10), 5: (17, 18),
             14: (11, 12), 15: (8, 9), 16: (9, 10)}
    always = {4: (11, 12, 13), 7: (11,), 8: (9, 10), 9: (7,),
              12: (10, 11, 13), 13: (6,), 16: (11, 12, 13)}
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
                item.update(label_index=record[label_offset],
                            label=reference(record[label_offset], f'Widget{widget}LabelIndex'))
            if control & 15 == 5:
                item.update(status_index=record[status_offset],
                            status_text=reference(record[status_offset], f'Widget{widget}StatusTextIndex'))
        elif kind == 6:
            item['scene'] = record[6] + 1
            if label_type == 3:
                if item['scene'] not in scenes:
                    raise ValueError('Scene widget refers to an absent scene')
                item.update(label_index=scenes[item['scene']]['index'], label=scenes[item['scene']]['text'])
            if control & 15 == 5:
                item.update(status_index=record[12],
                            status_text=reference(record[12], f'Widget{widget}StatusTextIndex'))
        if kind in always:
            for offset in always[kind]:
                value = record[offset]
                if kind in (4, 16):
                    origin = f'Widget{widget}{("Low", "Medium", "High")[offset - 11]}StatusIndex'
                elif kind == 7:
                    origin = f'Widget{widget}LabelIndex'
                elif kind == 8:
                    origin = f'Widget{widget}{"Label" if offset == 9 else "StatusText"}Index'
                elif kind == 9:
                    origin = f'Widget{widget}LabelIndex'
                elif kind == 12:
                    origin = f'Widget{widget}{ {10: "Prefix", 11: "Suffix", 13: "Label"}[offset]}Index'
                else:
                    origin = f'Widget{widget}LabelIndex'
                content = reference(value, origin,
                                    measurement_empty=kind == 12 and offset == 13)
                if kind == 7:
                    item.update(label_index=value, label=content)
                elif kind == 8:
                    field = 'label' if offset == 9 else 'status'
                    item[field + '_index'] = value
                    item[field if field == 'label' else 'status_text'] = content
                elif kind == 9:
                    item.update(label_index=value, label=content)
                elif kind == 12:
                    field = {10: 'prefix', 11: 'suffix', 13: 'label'}[offset]
                    item[field + '_index'] = value
                    item[field] = content
                elif kind == 13:
                    item.update(label_index=value, label=content)
                elif kind == 16:
                    item.setdefault('level_statuses', []).append(
                        {'offset': offset, 'index': value, 'text': content})
                else:
                    item.setdefault('static_references', []).append(
                        {'offset': offset, 'index': value, 'text': content})
        if kind == 7 and control & 7 == 5:
            item.update(status_index=record[12],
                        status_text=reference(record[12], f'Widget{widget}StatusTextIndex'))
        if kind == 2:
            item['group'] = record[6]
            item['application'] = memory[17 if control & 128 else 16]
        if label_type in (1, 2):
            item['label_source'] = 'dynamic-cache-not-read'
        widgets.append(item)
    return {'page_mode': 'single' if nav == 0 else 'multiple', 'navigation_variant': nav_variant,
            'page_names': page_names, 'widgets': widgets,
            'static_strings': [{'index': i, 'text': value, 'uses': uses[i]}
                               for i, value in enumerate(strings)],
            'special_static_references': [
                {'index': index, 'meaning': 'measurement-empty-label' if index == 64 else 'unused',
                 'uses': origins}
                for index, origins in special_uses.items() if origins],
            'scenes': scenes, 'static_text_crc_verified': True, 'dynamic_labels_verified': False,
            'raw_static_text_crc_verified': expected == raw_crc,
            'static_text_crc_method': 'physical-bytes' if expected == raw_crc else 'toolkit-zero-padded-strings',
            'memory_sha256': hashlib.sha256(memory).hexdigest()}


def _edlt_static_labels(client, address, *, database_name=True, expected_serial=None):
    """Read one stable physical image without querying volatile label traffic."""
    address = _unit(address)
    metadata = _object(client, f'CMQTT UNIT {address}') if database_name else {}
    unit_type = _bytes(client, address, f'UNIT IDENTIFY {address} 1', attribute=1).decode('ascii').strip(' \0')
    firmware = _bytes(client, address, f'UNIT IDENTIFY {address} 2', attribute=2).decode('ascii').strip(' \0')
    if not _supported_edlt(unit_type, firmware):
        raise ValueError(f'Unsupported physical eDLT identity: {unit_type} {firmware}')
    serial_evidence = None
    if expected_serial is not None:
        from .serials import parse_native_serial
        expected = parse_native_serial(expected_serial)
        if not expected.known:
            raise ValueError('Fresh inventory did not provide a known physical serial')
        serial_before, identify_before = _physical_serial(client, address)
        if serial_before != expected.canonical:
            raise ValueError(
                f'Physical serial {serial_before} differs from fresh inventory serial {expected.canonical}')
    before = read_memory(client, address, 0, 16)
    memory = read_memory(client, address, 0, 9216)
    after = read_memory(client, address, 0, 16)
    if before != memory[:16] or before != after:
        raise ValueError('eDLT configuration changed during the read; retry the snapshot')
    if expected_serial is not None:
        serial_after, identify_after = _physical_serial(client, address)
        if serial_after != expected.canonical or serial_after != serial_before:
            raise ValueError(
                f'Physical serial changed during the configuration read: '
                f'before={serial_before}, after={serial_after}, inventory={expected.canonical}')
        serial_evidence = {
            'serial': serial_after,
            'method': 'physical-identify4-before-and-after-memory',
            'before_data_hex': identify_before,
            'after_data_hex': identify_after,
            'stable': True,
        }
    return {'address': address, 'name': metadata.get('name'), 'unit_type': unit_type,
            'firmware': firmware, 'source': 'physical-via-cmqttd', 'configuration_header_stable': True,
            'physical_serial_verified': serial_evidence is not None,
            'physical_serial_evidence': serial_evidence,
            **decode_edlt_labels(memory)}


def edlt_labels(client, address):
    """Read one physical eDLT and retain the existing single-unit JSON shape."""
    result = _edlt_static_labels(client, address)
    address = result['address']
    observed = decode_observed_labels(_object(client, f'CMQTT LABELS {address}'))
    if observed['requested_address'] is not None and observed['requested_address'] != address:
        raise ValueError('cmqttd dynamic-label response does not match the requested unit-shaped address')
    return {**result, 'observed_dynamic_labels': observed,
            'dynamic_labels_observed': bool(observed['entries'])}


def _record_kind(record):
    """Classify one fresh native record for complete eDLT selection."""
    if (record.presence == 'absent' and record.status == 'absent'
            and not record.errors and record.state is None):
        return 'absent'
    ambiguous = (record.presence in {'duplicate_address', 'uncertain', 'multiple_error'}
                 or record.status == 'duplicate_serial')
    if ambiguous:
        return 'ambiguous'
    known = (record.presence == 'single' and record.status == 'ok'
             and not record.errors and record.state == 'ok'
             and isinstance(record.unit_type, str) and bool(record.unit_type)
             and isinstance(record.firmware, str) and bool(record.firmware))
    if not known:
        return 'unknown'
    if record.unit_type == 'KEYGL5' and not _supported_edlt(record.unit_type, record.firmware):
        return 'unsupported'
    if _supported_edlt(record.unit_type, record.firmware):
        return 'supported'
    return 'other'


def _error(address, error):
    return {'address': address, 'type': type(error).__name__, 'error': str(error)[:1024]}


def edlt_label_inventory(client, network):
    """Read every exact supported eDLT found by one fresh network scan.

    Physical images are necessarily sequential. Dynamic-label SAL observations
    are fetched once at network scope and are never attributed to a display.
    """
    network = _network(network)  # Validate before the first command.
    from .cgate import CGateError
    from .serials import NativeSerials
    inventory = NativeSerials(client).refresh(network)
    classified = {'unsupported': [], 'unknown': [], 'ambiguous': [], 'other': [], 'absent': []}
    supported = []
    for record in sorted(inventory.records, key=lambda item: item.address):
        kind = _record_kind(record)
        if kind == 'supported':
            supported.append(record)
        else:
            classified[kind].append(record.as_dict())

    units, read_errors = [], []
    connection_usable = True
    for position, record in enumerate(supported):
        address = f'{network}/p/{record.address}'
        try:
            unit = _edlt_static_labels(client, address, database_name=False,
                                       expected_serial=record.serial)
            unit['inventory_identity'] = record.as_dict()
            units.append(unit)
        except CGateError as error:
            # A complete 4xx/5xx reply keeps the tagged stream synchronized.
            read_errors.append(_error(address, error))
        except RuntimeError as error:
            # CGateClient closes after an incomplete, malformed or timed-out
            # reply. Never let a later request consume a late response.
            read_errors.append({**_error(address, error), 'connection_usable': False})
            for remaining in supported[position + 1:]:
                read_errors.append({'address': f'{network}/p/{remaining.address}',
                                    'type': 'NotAttempted',
                                    'error': 'A prior transport failure made the connection unusable'})
            connection_usable = False
            break
        except Exception as error:
            read_errors.append(_error(address, error))

    observed = None
    observation_error = None
    if connection_usable:
        try:
            observed = decode_observed_labels(_object(client, f'CMQTT LABELS {network}'))
            if observed['requested_address'] != network:
                raise ValueError('cmqttd dynamic-label response does not match the requested network')
        except Exception as error:
            observed = None
            observation_error = _error(network, error)
    else:
        observation_error = {'address': network, 'type': 'NotAttempted',
                             'error': 'A prior transport failure made the connection unusable'}

    inventory_complete = inventory.refresh_completed and inventory.complete
    selection_complete = (inventory_complete
                          and not classified['unsupported'] and not classified['unknown']
                          and not classified['ambiguous'])
    complete = (selection_complete and not read_errors
                and observation_error is None and len(units) == len(supported))
    return {
        'format': 'cbus-edlt-label-inventory-v1',
        'network': network,
        'source': 'physical-via-cmqttd',
        'complete': complete,
        'selection_complete': selection_complete,
        'inventory_complete': inventory_complete,
        'fresh_inventory': inventory.as_dict(),
        'supported_addresses': [record.address for record in supported],
        'units': units,
        'unsupported': classified['unsupported'],
        'unknown': classified['unknown'],
        'ambiguous': classified['ambiguous'],
        'absent': classified['absent'],
        'other_units': classified['other'],
        'read_errors': read_errors,
        'observed_dynamic_labels_scope': network,
        'observed_dynamic_labels': observed,
        'observation_error': observation_error,
        'dynamic_labels_observed': bool(observed and observed['entries']),
        'device_dynamic_label_cache_readback': False,
        'observations_complete': False,
        'network_snapshot_atomic': False,
        'physical_snapshots_sequential': True,
        'database_updated': False,
        'physical_device_modified': False,
    }
