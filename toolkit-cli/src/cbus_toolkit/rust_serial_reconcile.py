"""Independent, fail-closed admission of Rust routed apply-v2 frame evidence.

These captures cover commissioning frames, not every byte on the connection.
No transport, device, or project I/O occurs while reconstructing observations.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .pci import Confirmation, Frame, FrameStream, IdentifyCAL, RecallCAL, ReplyCAL, ProtocolError, decode_frame, encode_command
from .pci_inventory import MMIBlock, _MMIStream, _decode_line
from .pci_routing import RoutedCALCommand, encode_routed_install_mmi, reply_network_route
from .pci_selected_serial import (
    ATTEMPT_FORMAT, ATTEMPT_SCOPES, MAX_JOURNAL_BYTES, SelectedSerialPlan,
    _canonical_fingerprint, _hex, _inventory_proof, _json, _keys,
)
from .pci_serial_address import _selected_serial, decode_serial_address_receipt, encode_serial_address

FORMAT = 'cbus-selected-serial-apply-v2'
_TOP = ('format operation state outcome serial destination local_unit endpoint options_verified '
        'send_intent_recorded attempt_recorded attempt_durability_verified send_attempted '
        'exchange_send_attempted send_completed sends receipt_matched exchange_termination '
        'exchange_errors after_outcome after_collection_complete after_unexpected_changes '
        'after_errors errors attempt_identity plan route_binding journal reconciliation_evidence').split()
_CAPTURE = ('format source request_hex confirmation raw_frames_hex parser_frames_hex ignored_frames_hex '
            'complete stream_complete termination').split()


def _same(actual, expected, label):
    if _json(actual) != _json(expected):
        raise ValueError(label + ' differs from independently verified evidence')


def _capture(value, request, termination, *, checksum, limit=65536, positive=True):
    _keys(value, _CAPTURE, 'Rust frame capture')
    for key, wanted in {'format': 'cbus-selected-serial-frame-capture-v1',
                        'source': 'cbus-transport-strict-selected-serial',
                        'ignored_frames_hex': [], 'complete': True, 'stream_complete': True,
                        'termination': termination}.items():
        _same(value[key], wanted, 'Capture ' + key)
    if len(_json(value).encode('utf-8')) > 65536:
        raise ValueError('Serialized frame capture exceeds 64 KiB')
    token = value['confirmation']
    if not isinstance(token, str) or not re.fullmatch('[g-z]', token):
        raise ValueError('Capture confirmation is not one allocated g-z token')
    confirmation = token.encode('ascii')
    _same(value['request_hex'], (request[:-2] + confirmation + request[-1:]).hex(), 'Capture request')
    originals, normalized = value['raw_frames_hex'], value['parser_frames_hex']
    if not isinstance(originals, list) or not isinstance(normalized, list) or len(originals) != len(normalized):
        raise ValueError('Raw and parser captures must have one-to-one frames')
    raw_parts, parser_parts = [], []
    for original, parser in zip(originals, normalized):
        raw, cooked = _hex(original, limit), _hex(parser, limit)
        if re.fullmatch(b'[g-z][.#$%!]', raw):
            if cooked != raw:
                raise ValueError('Confirmation bytes were changed')
        else:
            body = raw.rstrip(b'\r\n')
            if not body or raw[len(body):] not in (b'\r', b'\n', b'\r\n'):
                raise ValueError('Original frame requires one CR, LF or CRLF terminator')
            if not re.fullmatch(b'[0-9A-F]+', body) or len(body) % 2:
                raise ValueError('Captured frame is not uppercase hexadecimal wire text')
            data = bytes.fromhex(body.decode('ascii'))
            unchanged = body + b'\r\n'
            appended = body + f'{(-sum(data)) & 255:02X}'.encode() + b'\r\n'
            if cooked != unchanged and cooked != appended:
                raise ValueError('Parser frame reencoded captured content')
            if cooked == appended and checksum:
                raise ValueError('Checksum-on capture cannot add a missing outer checksum')
            if cooked == unchanged and sum(data) & 255:
                raise ValueError('Retained outer checksum is invalid')
            if cooked == appended and not sum(data) & 255:
                # A zero checksum may also belong to checksum-free content.
                # Reject addition when the original is already a valid frame.
                for parse in (lambda: decode_frame(body, checksum=True, routed=True),
                              lambda: _decode_line(body)):
                    try:
                        parse()
                    except (ProtocolError, ValueError):
                        continue
                    raise ValueError('Checksum appended to a valid checksummed frame')
        raw_parts.append(raw)
        parser_parts.append(cooked)
    if sum(map(len, raw_parts)) > limit or sum(map(len, parser_parts)) > limit:
        raise ValueError('Capture exceeds its byte bound')
    if positive and (not parser_parts or parser_parts[0] != confirmation + b'.' or
                     sum(part == confirmation + b'.' for part in parser_parts) != 1):
        raise ValueError('Observation requires exactly one positive confirmation first')
    return b''.join(parser_parts), confirmation


def _events(raw, route=(), local=None, mmi=False):
    stream = _MMIStream(route, local) if mmi else FrameStream(routed=bool(route))
    events = []
    for byte in raw:
        events.extend(stream.feed_byte(byte) if mmi else stream.feed(bytes([byte])))
    if stream.buffer:
        raise ValueError('Capture has an incomplete parser tail')
    return events


def _identity(capture, address, local, checksum, route=()):
    request = (RoutedCALCommand(address, IdentifyCAL(4), bridges=route).encode(confirmation=b'g', checksum=checksum)
               if route else encode_command(address, IdentifyCAL(4), confirmation=b'g', checksum=checksum))
    raw, token = _capture(capture, request, 'quiet_window_elapsed', checksum=checksum)
    events = _events(raw, route)
    if not events or events[0] != Confirmation(token, '.'):
        raise ValueError('Missing identity confirmation')
    if (not route and len(events) != 2) or len(events) > 8:
        raise ValueError('Direct PCI identity requires one reply; remote identity allows at most seven')
    found = {}
    for frame in events[1:]:
        if not isinstance(frame, Frame) or len(frame.cals) != 1:
            raise ValueError('Unexpected identity event')
        if frame.bare:
            if route or address != local:
                raise ValueError('Bare identity cannot identify a remote unit')
        elif route:
            if (frame.source, frame.destination, frame.route) != (route[0], local, reply_network_route(route, address)):
                raise ValueError('Identity Reply Network mismatch')
        elif (frame.source, frame.destination) != (address, local) or frame.route not in (b'\x00', b'\x01\x00'):
            raise ValueError('Local identity source/destination mismatch')
        if not frame.bare and bytes.fromhex(frame.raw.decode('ascii'))[0] != 0x86:
            raise ValueError('Identity requires response header 86')
        cal = frame.cals[0]
        if not isinstance(cal, ReplyCAL) or cal.parameter != 4 or len(cal.data) != 12:
            raise ValueError('Identity requires exact IDENTIFY4 reply')
        packed = int.from_bytes(cal.data[5:9], 'big')
        serial, _ = _selected_serial(f'{packed >> 12}.{packed & 4095}')
        if serial in found and found[serial] != cal.data:
            raise ValueError('Serial identity blocks conflict')
        found[serial] = cal.data
    if not found:
        raise ValueError('Present address has no known identity')
    return sorted(found, key=lambda s: tuple(map(int, s.split('.'))))


def _inventory(value, plan):
    _keys(value, ('format', 'route', 'local_unit', 'local_identity', 'initial_mmi',
                  'serial_observations', 'final_mmi'), 'Rust inventory')
    _same(value['format'], 'cbus-selected-serial-inventory-frames-v1', 'Inventory format')
    route, local, checksum = tuple(plan['route']), plan['local_unit'], plan['settings']['command_checksum']
    _same(value['route'], list(route), 'Inventory route')
    _same(value['local_unit'], local, 'Inventory local unit')
    _same(_identity(value['local_identity'], local, local, checksum), [plan['expected_local_serial']], 'Inventory PCI identity')
    bookends = []
    for key in ('initial_mmi', 'final_mmi'):
        raw, token = _capture(value[key], encode_routed_install_mmi(route, checksum=checksum),
                              'coverage_complete', checksum=checksum)
        events = _events(raw, route, local, True)
        if not events or events[0] != Confirmation(token, '.'):
            raise ValueError('Missing MMI confirmation')
        states = []
        for block in events[1:]:
            if not isinstance(block, MMIBlock) or block.application != 255 or block.start != len(states):
                raise ValueError('MMI coverage has gaps, overlap or foreign blocks')
            states.extend(block.states)
        if len(states) != 256 or 3 in states:
            raise ValueError('MMI must cover all 256 healthy states')
        bookends.append(states)
    _same(bookends[0], bookends[1], 'MMI bookends')
    observations = value['serial_observations']
    if not isinstance(observations, list):
        raise ValueError('Serial observations must be a list')
    identities, seen = [], set()
    for observation in observations:
        _keys(observation, ('address', 'capture'), 'Rust identity probe')
        address = observation['address']
        if type(address) is not int or not 0 <= address <= 255:
            raise ValueError('Invalid probe address')
        serials = _identity(observation['capture'], address, local, checksum, route)
        if seen.intersection(serials):
            raise ValueError('Serial appears at multiple addresses')
        seen.update(serials)
        identities.append({'address': address, 'serials': serials})
    _same([item['address'] for item in identities], [a for a, state in enumerate(bookends[0]) if state], 'All present probes')
    return {'states': bookends[0], 'identities': identities}


def verify_rust_journal(path, raw=None, value=None):
    """Return a VerifiedMove only for a complete routed v2 journal and marker."""
    # Lazy import keeps serial_reconcile's dispatcher free of import cycles.
    from .serial_reconcile import ReconcileError, VerifiedMove, _parse, _read_bounded
    path = Path(path)
    try:
        if path.is_symlink():
            raise ValueError("Journal file symlinks are not an admitted location")
        if raw is None:
            raw = _read_bounded(path, MAX_JOURNAL_BYTES)
        if value is None:
            value = _parse(raw, 'Rust selected-serial journal')
        _keys(value, _TOP, 'Rust apply journal')
        _same(value['format'], FORMAT, 'Journal format')
        plan = SelectedSerialPlan.from_dict(value['plan']).as_dict()
        _same(value['plan'], plan, 'Canonical journal plan')
        if not plan.get('route'):
            raise ValueError('Rust v2 reconciliation requires a routed plan')
        fixed = {'operation': 'apply', 'state': 'after_observed', 'outcome': 'observed_expected_change',
                 'options_verified': [5], 'sends': 1, 'exchange_termination': 'response_window_elapsed',
                 'exchange_errors': [], 'after_outcome': 'observed_expected_change',
                 'after_collection_complete': True, 'after_unexpected_changes': [], 'after_errors': [], 'errors': []}
        fixed.update({key: True for key in ('send_intent_recorded', 'attempt_recorded',
                     'attempt_durability_verified', 'send_attempted', 'exchange_send_attempted', 'send_completed')})
        fixed.update({key: plan[key] for key in ('serial', 'destination', 'local_unit', 'endpoint')})
        for key, wanted in fixed.items():
            _same(value[key], wanted, 'Journal ' + key)
        if type(value['receipt_matched']) is not bool:
            raise ValueError('Receipt match must be a boolean')
        binding = value['route_binding']
        _keys(binding, ('project_path', 'project_sha256', 'source_network', 'target_network',
                        'route', 'route_rederived', 'physical_bridge_acceptance_verified'), 'Rust route binding')
        if not isinstance(binding['project_path'], str) or not Path(binding['project_path']).is_absolute():
            raise ValueError('Route project path must be absolute')
        for key in ('source_network', 'target_network'):
            if type(binding[key]) is not int or not 0 <= binding[key] <= 255:
                raise ValueError('Route network must be an integer in 0..255')
        if binding['source_network'] == binding['target_network']:
            raise ValueError('Route networks must differ')
        for key, wanted in {'project_sha256': plan['project_sha256'], 'route': plan['route'],
                            'route_rederived': True, 'physical_bridge_acceptance_verified': False}.items():
            _same(binding[key], wanted, 'Route binding ' + key)
        proof = value['reconciliation_evidence']
        _keys(proof, ('format', 'source', 'frame_capture_scope', 'raw_connection_capture',
                      'before', 'local_identity', 'local_options', 'exchange', 'after'), 'Rust reconciliation evidence')
        for key, wanted in {'format': 'cbus-rust-selected-serial-reconciliation-v1',
                            'source': 'cbus-transport-routed-selected-serial',
                            'frame_capture_scope': 'commissioning_frames', 'raw_connection_capture': False}.items():
            _same(proof[key], wanted, 'Reconciliation evidence ' + key)
        local, checksum, route = plan['local_unit'], plan['settings']['command_checksum'], tuple(plan['route'])
        before = _inventory(proof['before'], plan)
        _same(before, _inventory_proof(plan['before'], plan['endpoint'], local, checksum, route), 'Fresh before inventory')
        _same(_identity(proof['local_identity'], local, local, checksum), [plan['expected_local_serial']], 'Fresh PCI identity')
        options_raw, token = _capture(proof['local_options'],
            encode_command(local, RecallCAL(66, 1), confirmation=b'g', checksum=checksum),
            'quiet_window_elapsed', checksum=checksum, limit=4096)
        events = _events(options_raw)
        if len(events) != 2 or events[0] != Confirmation(token, '.'):
            raise ValueError('Local options require one confirmation and one reply')
        frame = events[1]
        if (not isinstance(frame, Frame) or len(frame.cals) != 1 or
                (not frame.bare and ((frame.source, frame.destination) != (local, local) or
                                    frame.route not in (b'\x00', b'\x01\x00')))):
            raise ValueError('Local options reply is not pinned to the direct PCI')
        if not frame.bare and bytes.fromhex(frame.raw.decode('ascii'))[0] != 0x86:
            raise ValueError('Options require response header 86')
        cal = frame.cals[0]
        if not isinstance(cal, ReplyCAL) or cal.parameter != 66 or cal.data != b'\x05':
            raise ValueError('Local options must be exactly parameter 66 byte 05')
        exchange, token = _capture(proof['exchange'], encode_serial_address(plan['serial'], plan['destination'],
            command_checksum=checksum, bridges=route), 'response_window_elapsed',
            checksum=checksum, limit=4096, positive=False)
        receipt = decode_serial_address_receipt(exchange, serial=plan['serial'], destination=plan['destination'],
                                               local_unit=local, confirmation=token, bridges=route)
        if receipt.errors or receipt.pending:
            raise ValueError('Exchange contains invalid framing or incomplete parser bytes')
        _same(value['receipt_matched'], receipt.matched, 'Receipt match')
        _same(_inventory(proof['after'], plan), plan['expected_after'], 'Fresh after inventory')
        recorded = value['journal']
        if not isinstance(recorded, str) or not Path(recorded).is_absolute():
            raise ValueError('Journal location must be an absolute string')
        if Path(recorded) != path.absolute():
            raise ValueError('Journal was relocated from its bound path')
        # Rust canonicalizes the parent only, preserving the journal filename.
        # Resolving the file itself would admit a symlink/relocation bypass.
        canonical_journal = Path(recorded).parent.resolve(strict=True) / Path(recorded).name
        fingerprint = _canonical_fingerprint(plan)
        marker = value['attempt_identity']
        if (not isinstance(marker, str) or not Path(marker).is_absolute() or
                Path(marker).name != f'.cbus-selected-serial-attempt-sha256-{fingerprint}.json'):
            raise ValueError('Attempt marker does not name the canonical plan fingerprint')
        if Path(marker).is_symlink():
            raise ValueError('Attempt marker file symlinks are not admitted')
        record = _parse(_read_bounded(marker, MAX_JOURNAL_BYTES), 'Rust attempt marker')
        _keys(record, ('format', 'operation', 'attempt_id', 'scope', 'journal', 'plan',
                       'send_may_have_occurred', 'read_only_recovery_only'), 'Rust attempt marker')
        for key, wanted in {'format': ATTEMPT_FORMAT, 'operation': 'apply',
                            'attempt_id': 'sha256:' + fingerprint, 'journal': str(canonical_journal),
                            'plan': plan, 'send_may_have_occurred': True, 'read_only_recovery_only': True}.items():
            _same(record[key], wanted, 'Attempt marker ' + key)
        scope = record['scope']
        if scope not in ATTEMPT_SCOPES or scope != ('resolved_journal_directory' if Path(marker).parent.resolve(strict=True) == canonical_journal.parent
                                                   else 'operator_selected_attempt_store'):
            raise ValueError('Attempt marker scope does not match its journal directory')
        return VerifiedMove(str(path.absolute()), hashlib.sha256(raw).hexdigest(), record['attempt_id'], marker,
                            plan['serial'], plan['source'], plan['destination'], dict(plan['endpoint']), local,
                            receipt.matched, route, plan['project_sha256'], binding['source_network'], binding['target_network'])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReconcileError(f'Rust routed journal evidence is incomplete or inconsistent: {error}') from error
