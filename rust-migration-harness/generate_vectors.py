#!/usr/bin/env python3
"""Golden test vector generator for the C-Bus Rust migration.

Uses the *current working tree* Python implementation as ground truth.
Every vector is self-checked against Python at generation time: decode
vectors are produced by encoding known packets (or hand-written wires) and
then decoding them back; the decoded structure, consumed byte count and
re-encoded bytes are all captured.

Run from the repo root with the project venv:

    .venv/bin/python rust-migration-harness/generate_vectors.py

Outputs (committed to git):
    rust-migration-harness/vectors/*.jsonl
    rust-migration-harness/fixtures/behavioral_expectations.json
"""
import asyncio
import json
import os
import sys
from datetime import date, time

HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HARNESS_DIR)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(HARNESS_DIR, 'lib'))

import warnings
warnings.simplefilter('ignore')  # decode of lossy vectors emits UserWarnings

from cbus.common import (
    Application, CONFIRMATION_CODES, GroupState, PriorityClass,
    add_cbus_checksum, cbus_checksum, duration_to_ramp_rate,
    ramp_rate_to_duration, _LIGHT_RAMP_RATES)
from cbus.protocol.packet import decode_packet
from cbus.protocol.base_packet import BasePacket, InvalidPacket
from cbus.protocol.confirm_packet import ConfirmationPacket
from cbus.protocol.dm_packet import DeviceManagementPacket
from cbus.protocol.pm_packet import PointToMultipointPacket
from cbus.protocol.pp_packet import PointToPointPacket
from cbus.protocol.reset_packet import ResetPacket
from cbus.protocol.scs_packet import SmartConnectShortcutPacket
from cbus.protocol.cal.extended import ExtendedCAL
from cbus.protocol.cal.identify import IdentifyCAL
from cbus.protocol.cal.recall import RecallCAL
from cbus.protocol.cal.reply import ReplyCAL
from cbus.protocol.cal.report import (
    BinaryStatusReport, LevelStatusReport, manchester_encode)
from cbus.protocol.application.clock import (
    ClockRequestSAL, ClockUpdateSAL, clock_update_sal)
from cbus.protocol.application.enable import EnableSetNetworkVariableSAL
from cbus.protocol.application.lighting import (
    LightingOffSAL, LightingOnSAL, LightingRampSAL, LightingTerminateRampSAL)
from cbus.protocol.application.status_request import StatusRequestSAL
from cbus.protocol.application.temperature import TemperatureBroadcastSAL
from cbus.daemon.topics import (
    ga_string, set_topic, state_topic, conf_topic,
    bin_sensor_state_topic, bin_sensor_conf_topic)
from cbus.daemon.mqtt_gateway import MqttClient, get_topic_group_address

from pyjson import packet_to_json, sal_to_json, cal_to_json

END_RESPONSE = b'\r\n'
END_COMMAND = b'\r'

VEC_DIR = os.path.join(HARNESS_DIR, 'vectors')
FIX_DIR = os.path.join(HARNESS_DIR, 'fixtures')

_counters = {}


def _vid(prefix: str, slug: str) -> str:
    n = _counters.get(prefix, 0) + 1
    _counters[prefix] = n
    return f'{prefix}-{n:04d}-{slug}'


class VectorError(Exception):
    pass


# ---------------------------------------------------------------------------
# decode vector construction + self check
# ---------------------------------------------------------------------------

def make_decode_vector(prefix, slug, wire: bytes, *, checksum=True,
                       strict=True, from_pci=True, note='',
                       expect_reencodable=True):
    """Decode `wire` with Python, record the result as a vector."""
    p, consumed = decode_packet(
        wire, checksum=checksum, strict=strict, from_pci=from_pci)
    pj = packet_to_json(p)

    reencode = None
    if expect_reencodable and p is not None and pj is not None \
            and pj.get('type') not in ('invalid', 'cal'):
        try:
            out = p.encode_packet()
            reencode = out.decode('latin-1')
        except (NotImplementedError, ValueError):
            reencode = None

    return {
        'id': _vid(prefix, slug),
        'wire_hex': wire.hex(),
        'checksum': checksum,
        'strict': strict,
        'from_pci': from_pci,
        'expect_consumed': consumed,
        'expect_packet': pj,
        'expect_reencode': reencode,
        'note': note,
    }


def server_wire(p: BasePacket, source_address=None) -> bytes:
    """Serialize a packet the way a PCI (server) puts it on the wire."""
    if source_address is not None:
        p.source_address = source_address
    return p.encode_packet() + END_RESPONSE


def client_wire(p: BasePacket, confirmation=None, basic=False) -> bytes:
    """Serialize a packet the way a client (cmqttd) puts it on the wire.

    Mirrors PCIProtocol._prepare_packet: smart-mode packets get a
    backslash prefix; special packets (reset etc.) are bare; an optional
    confirmation character is appended before the CR.
    """
    from cbus.protocol.base_packet import SpecialClientPacket
    body = p.encode_packet()
    if not isinstance(p, SpecialClientPacket) and not basic:
        body = b'\\' + body
    if confirmation:
        body += confirmation
    return body + END_COMMAND


# ---------------------------------------------------------------------------
# suite: decode_from_pci
# ---------------------------------------------------------------------------

def gen_decode_from_pci():
    vecs = []
    P = 'fp'

    # -- transport-level specials ------------------------------------------
    vecs.append(make_decode_vector(P, 'power-on', b'+'))
    vecs.append(make_decode_vector(P, 'power-on-double', b'++', note='consumes only 1 byte'))
    vecs.append(make_decode_vector(P, 'pci-error', b'!'))
    for code in CONFIRMATION_CODES:
        vecs.append(make_decode_vector(
            P, f'confirm-{chr(code)}-ok', bytes([code]) + b'.'))
        vecs.append(make_decode_vector(
            P, f'confirm-{chr(code)}-fail', bytes([code]) + b'#'))
    vecs.append(make_decode_vector(P, 'empty-needs-more', b''))
    vecs.append(make_decode_vector(P, 'incomplete-no-crlf', b'0538'))
    vecs.append(make_decode_vector(P, 'empty-line', b'\r\n'))

    # -- PM lighting on/off/terminate --------------------------------------
    sources = [1, 5, 99, 200, 255]
    apps = [0x30, 0x38, 0x45, 0x5F]
    gas = [0, 1, 2, 63, 64, 127, 128, 200, 254, 255]
    ctors = [('on', LightingOnSAL), ('off', LightingOffSAL),
             ('term', LightingTerminateRampSAL)]
    i = 0
    for app in apps:
        for ga in gas:
            for name, ctor in ctors:
                src = sources[i % len(sources)]
                i += 1
                p = PointToMultipointPacket(sals=[ctor(ga, app)])
                vecs.append(make_decode_vector(
                    P, f'pm-light-{name}-app{app:02x}-ga{ga}',
                    server_wire(p, src)))

    # -- PM lighting ramps: every ramp rate --------------------------------
    levels = [0, 1, 127, 128, 254, 255]
    ramp_gas = [1, 100, 255]
    i = 0
    for code, duration in sorted(_LIGHT_RAMP_RATES.items()):
        for level in levels:
            ga = ramp_gas[i % len(ramp_gas)]
            app = [0x38, 0x30][i % 2]
            src = sources[i % len(sources)]
            i += 1
            p = PointToMultipointPacket(
                sals=[LightingRampSAL(ga, app, duration, level)])
            vecs.append(make_decode_vector(
                P, f'pm-ramp-{int(code):02x}-lvl{level}',
                server_wire(p, src)))

    # -- PM multi-SAL packets ----------------------------------------------
    for count in (2, 3, 5, 9):
        sals = []
        for k in range(count):
            sals.append([LightingOnSAL, LightingOffSAL][k % 2](k + 1, 0x38))
        p = PointToMultipointPacket(sals=sals)
        vecs.append(make_decode_vector(
            P, f'pm-multi-{count}sal', server_wire(p, 10)))
    p = PointToMultipointPacket(sals=[
        LightingOnSAL(1, 0x38),
        LightingRampSAL(2, 0x38, 12, 128),
        LightingOffSAL(3, 0x38)])
    vecs.append(make_decode_vector(P, 'pm-multi-mixed', server_wire(p, 11)))

    # -- PM without checksum (PCI in no-SRCHK mode) ------------------------
    for ga in (1, 100, 255):
        p = PointToMultipointPacket(checksum=False,
                                    sals=[LightingOnSAL(ga, 0x38)])
        vecs.append(make_decode_vector(
            P, f'pm-nochecksum-ga{ga}', server_wire(p, 3), checksum=False))

    # -- PM clock ----------------------------------------------------------
    for (h, m, s) in [(0, 0, 0), (12, 30, 45), (23, 59, 59), (6, 7, 8)]:
        p = PointToMultipointPacket(sals=[ClockUpdateSAL(time(h, m, s))])
        vecs.append(make_decode_vector(
            P, f'pm-clock-time-{h:02}{m:02}{s:02}', server_wire(p, 1)))
    for (y, mo, d) in [(2000, 1, 1), (2026, 7, 20), (2099, 12, 31),
                       (2024, 2, 29)]:
        p = PointToMultipointPacket(sals=[ClockUpdateSAL(date(y, mo, d))])
        vecs.append(make_decode_vector(
            P, f'pm-clock-date-{y}{mo:02}{d:02}', server_wire(p, 1)))
    # combined date+time (what timesync sends)
    from datetime import datetime
    p = PointToMultipointPacket(
        sals=clock_update_sal(datetime(2026, 7, 20, 10, 20, 30)))
    vecs.append(make_decode_vector(P, 'pm-clock-datetime', server_wire(p, 1)))
    p = PointToMultipointPacket(sals=[ClockRequestSAL()])
    vecs.append(make_decode_vector(P, 'pm-clock-request', server_wire(p, 20)))
    # time wire with dst byte 0x00 instead of 0xFF (decode must ignore dst)
    body = bytes([0x05, 0x01, 0xDF, 0x00, 0x0D, 0x01, 0x0A, 0x14, 0x1E, 0x00])
    wire = add_cbus_checksum(body).hex().upper().encode() + END_RESPONSE
    vecs.append(make_decode_vector(
        P, 'pm-clock-time-dst0', wire, expect_reencodable=False,
        note='dst byte 0x00 on wire; python re-encodes dst as 0xFF'))

    # -- PM temperature ----------------------------------------------------
    for ga in (0, 1, 100, 255):
        for tb in (0, 1, 2, 100, 254, 255):
            p = PointToMultipointPacket(
                sals=[TemperatureBroadcastSAL(ga, tb / 4.0)])
            vecs.append(make_decode_vector(
                P, f'pm-temp-ga{ga}-x{tb}', server_wire(p, 30)))

    # -- PM enable ---------------------------------------------------------
    for var in (0, 1, 127, 255):
        for val in (0, 66, 255):
            p = PointToMultipointPacket(
                sals=[EnableSetNetworkVariableSAL(var, val)])
            vecs.append(make_decode_vector(
                P, f'pm-enable-{var}-{val}', server_wire(p, 31)))

    # -- PM status request (as seen on the network) ------------------------
    for level in (False, True):
        for app in (0x38, 0x30, 0xFF):
            for block in (0, 32, 224):
                p = PointToMultipointPacket(sals=[StatusRequestSAL(
                    level_request=level, group_address=block,
                    child_application=app)])
                vecs.append(make_decode_vector(
                    P, f'pm-statusreq-{"lvl" if level else "bin"}'
                       f'-app{app:02x}-b{block}',
                    server_wire(p, 40)))
    # deprecated 0xFA form (decode-only; python re-encodes as 0x7A)
    body = bytes([0x05, 0x28, 0xFF, 0x00, 0xFA, 0x38, 0x20])
    wire = add_cbus_checksum(body).hex().upper().encode() + END_RESPONSE
    vecs.append(make_decode_vector(
        P, 'pm-statusreq-fa-form', wire, expect_reencodable=False,
        note='0xFA deprecated form; re-encode canonicalises to 0x7A'))
    # invalid block start (not multiple of 0x20) -> InvalidPacket
    body = bytes([0x05, 0x28, 0xFF, 0x00, 0x7A, 0x38, 0x21])
    wire = add_cbus_checksum(body).hex().upper().encode() + END_RESPONSE
    vecs.append(make_decode_vector(
        P, 'pm-statusreq-bad-block', wire,
        note='group_address & 0x1f != 0 raises -> invalid'))

    # -- unregistered application -> invalid --------------------------------
    body = bytes([0x05, 0x09, 0xCA, 0x00, 0x02, 0x25, 0x64])
    wire = add_cbus_checksum(body).hex().upper().encode() + END_RESPONSE
    vecs.append(make_decode_vector(
        P, 'pm-unregistered-app-ca', wire,
        note='application 0xCA (trigger/hvac) has no handler -> invalid'))
    # PM with routing byte != 0 -> invalid
    body = bytes([0x05, 0x09, 0x38, 0x01, 0x79, 0x01])
    wire = add_cbus_checksum(body).hex().upper().encode() + END_RESPONSE
    vecs.append(make_decode_vector(
        P, 'pm-nonzero-routing', wire,
        note="data[1] != 0x00 raises 'Routing data in PM message?'"))

    # -- PP packets ---------------------------------------------------------
    for unit in (0, 1, 16, 254):
        for attr in range(0x00, 0x12):
            p = PointToPointPacket(unit_address=unit,
                                   cals=[IdentifyCAL(attr)])
            vecs.append(make_decode_vector(
                P, f'pp-identify-u{unit}-a{attr:02x}', server_wire(p, 1)))
            if unit != 16:
                break  # full attr sweep only for unit 16
    for (param, count) in [(0x10, 4), (0x3E, 1), (0xFA, 44), (0xFB, 9),
                           (0x20, 12), (0x2C, 12), (0x23, 6), (0x2A, 6)]:
        p = PointToPointPacket(unit_address=16,
                               cals=[RecallCAL(param, count)])
        vecs.append(make_decode_vector(
            P, f'pp-recall-{param:02x}-{count}', server_wire(p, 1)))
    # PP reply CALs (unit-addressed form, like `86...` interrogation replies)
    for dlen in (0, 1, 4, 8, 9, 12, 20, 30):
        data = bytes((0x40 + i) & 0xff for i in range(dlen))
        p = PointToPointPacket(unit_address=0x10,
                               cals=[ReplyCAL(0x01, data)])
        vecs.append(make_decode_vector(
            P, f'pp-reply-len{dlen}', server_wire(p, 1)))
    # multi-CAL PP packet
    p = PointToPointPacket(unit_address=5, cals=[
        IdentifyCAL(0x01), IdentifyCAL(0x02)])
    vecs.append(make_decode_vector(P, 'pp-multi-cal', server_wire(p, 1)))

    # -- PP extended status (EXSTAT) golden literals from the test suite ---
    for slug, wire in [
        ('exstat-s91-block0',
         b'86999900F9003800A8AA0200000000000000000000000000000000000000C3'),
        ('exstat-s91-block88',
         b'86999900F900385800000000000000000000000000000000000000000000BF'),
        ('exstat-s91-block176',
         b'86999900F70038B0000000000000000000000000000000000000000069'),
        ('exstat-level-block0',
         b'86FFFF00F90738000000AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA00000000A4'),
        ('exstat-level-block11',
         b'86FFFF00F907380B0000000000000000000000000000000000000000000039'),
        ('exstat-level-block22',
         b'86FFFF00F7073816000000000000000000000000000000000000000030'),
        ('exstat-level-real',
         b'86141000F9403800AAAAAAA66A5666AA65A60A'
         b'00000000000000000000005C'),
    ]:
        vecs.append(make_decode_vector(P, slug, wire + END_RESPONSE,
                                       note='golden literal from pytest suite'))

    # -- PP EXSTAT generated level report sweeps ---------------------------
    for start in range(0, 256, 32):
        levels = [(start + k) & 0xff for k in range(8)]
        cal = ExtendedCAL(False, 0x38, start, LevelStatusReport(levels))
        p = PointToPointPacket(unit_address=0x10, cals=[cal])
        vecs.append(make_decode_vector(
            P, f'pp-exstat-levels-{start}', server_wire(p, 0x14)))
    # levels with missing (None) entries
    cal = ExtendedCAL(False, 0x38, 0, LevelStatusReport(
        [None, 0, 255, None, 128, 1, None, 254]))
    p = PointToPointPacket(unit_address=0x10, cals=[cal])
    vecs.append(make_decode_vector(
        P, 'pp-exstat-levels-missing', server_wire(p, 0x14)))
    # externally initiated flag
    cal = ExtendedCAL(True, 0x38, 32, LevelStatusReport([1, 2, 3, 4]))
    p = PointToPointPacket(unit_address=0x10, cals=[cal])
    vecs.append(make_decode_vector(
        P, 'pp-exstat-extinit', server_wire(p, 0x14)))
    # binary report sweep
    states = [GroupState.MISSING, GroupState.ON, GroupState.OFF,
              GroupState.ERROR] * 4
    cal = ExtendedCAL(False, 0x38, 64, BinaryStatusReport(states))
    p = PointToPointPacket(unit_address=0x10, cals=[cal])
    vecs.append(make_decode_vector(
        P, 'pp-exstat-binary-all-states', server_wire(p, 0x14)))
    # manchester invalid nibble on the wire decodes as None; python
    # re-encodes missing as 0x0000, so reencode differs from wire.
    inner = bytes([0x86, 0x14, 0x10, 0x00])  # flags, src, unit, 00
    cal_payload = bytes([0x07, 0x38, 0x00]) + b'\x1f\x00\xaa\xaa'
    cal_bytes = bytes([0xE0 | len(cal_payload)]) + cal_payload
    wire = add_cbus_checksum(inner + cal_bytes)
    wire = wire.hex().upper().encode() + END_RESPONSE
    vecs.append(make_decode_vector(
        P, 'pp-exstat-manchester-invalid', wire, expect_reencodable=False,
        note='invalid manchester nibbles decode to null level'))

    # -- PP bridged (decode-only; encode raises NotImplementedError) -------
    for blen_code, nhops in [(0x09, 0), (0x12, 1), (0x1B, 2), (0x24, 3),
                             (0x2D, 4), (0x36, 5)]:
        hops = bytes(range(0x50, 0x50 + nhops))
        inner = (bytes([0x06, 0x22, 0xAA, blen_code]) + hops +
                 bytes([0x33]) + bytes([0x21, 0x02]))
        wire = add_cbus_checksum(inner).hex().upper().encode() + END_RESPONSE
        vecs.append(make_decode_vector(
            P, f'pp-bridged-{nhops}hops', wire, expect_reencodable=False,
            note='bridged PP decode; encode is NotImplemented in python'))

    # -- direct CAL replies (headerless; working-tree packet.py behaviour) --
    for slug, wire in [
        ('direct-reply-type-name', b'890150435F434E49454421'),
        ('direct-reply-dm', b'8220104E'),
        ('direct-reply-gav', b'872AB64CF6BB1A9EE4'),
    ]:
        vecs.append(make_decode_vector(
            P, slug, wire + END_RESPONSE, expect_reencodable=False,
            note='direct CAL reply (flags byte is CAL header); '
                 'source_address=None unit_address=0'))
    # generated: reply lengths whose header low-3-bits avoid the
    # 3/5/6 address-type collision (and 0x20 dp bit is never set for
    # REPLY headers 0x81..0x9F)
    for dlen in (0, 1, 6, 8, 9, 14, 16, 22, 24, 30):
        data = bytes((i * 7) & 0xff for i in range(dlen))
        body = ReplyCAL(0x01, data).encode()
        if body[0] & 0x07 in (3, 5, 6):
            continue
        wire = add_cbus_checksum(body).hex().upper().encode() + END_RESPONSE
        vecs.append(make_decode_vector(
            P, f'direct-reply-len{dlen}', wire, expect_reencodable=False))

    # -- checksum failures --------------------------------------------------
    bad = bytearray(server_wire(PointToMultipointPacket(
        sals=[LightingOnSAL(1, 0x38)]), 9))
    # corrupt the checksum hex pair (second-to-last chars before CRLF)
    bad[-4:-2] = b'00' if bad[-4:-2] != b'00' else b'01'
    bad = bytes(bad)
    vecs.append(make_decode_vector(
        P, 'bad-checksum-strict', bad, note='strict: invalid packet'))
    vecs.append(make_decode_vector(
        P, 'bad-checksum-lenient', bad, strict=False,
        expect_reencodable=False,
        note='non-strict: warn and decode anyway (checksum stripped)'))

    # -- non-hex garbage ----------------------------------------------------
    vecs.append(make_decode_vector(
        P, 'non-hex-input', b'05zz0079\r\n', note='invalid: non-base16'))
    vecs.append(make_decode_vector(
        P, 'lowercase-hex-input', b'05380079ab\r\n',
        note='lowercase hex is NOT accepted'))
    return vecs


# ---------------------------------------------------------------------------
# suite: decode_to_pci  (client -> PCI parsing, from_pci=False)
# ---------------------------------------------------------------------------

def gen_decode_to_pci():
    vecs = []
    P = 'tp'

    def v(slug, wire, **kw):
        kw.setdefault('from_pci', False)
        vecs.append(make_decode_vector(P, slug, wire, **kw))

    # transport-level specials
    v('reset', b'~', checksum=False)
    v('smart-connect', b'|\r', checksum=False)
    v('smart-connect-double', b'||\r', checksum=False)
    v('toolkit-null', b'null', checksum=False,
      note='toolkit bug workaround: consume 4 bytes, no packet')
    v('cancel-question-mark', b'0538?\r', checksum=False,
      note='data before ? is discarded (s4.2.4)')
    v('empty-command', b'\r', checksum=False)

    # basic-mode once-off DM commands (@ prefix disables checksum)
    for (param, value) in [(0x21, 0xFF), (0x22, 0xFF), (0x42, 0x0E),
                           (0x30, 0x79), (0x30, 0x59), (0x3E, 0x00),
                           (0x41, 0x30)]:
        wire = f'@A3{param:02X}00{value:02X}\r'.encode()
        v(f'dm-basic-at-{param:02x}-{value:02x}', wire, checksum=True,
          note='@ prefix forces checksum off for this command')

    # basic-mode DM without @ (how cmqttd actually sends the init sequence)
    for (param, value), conf in [((0x21, 0xFF), b'h'), ((0x22, 0xFF), b'i'),
                                 ((0x42, 0x0E), b'j'), ((0x30, 0x79), b'k')]:
        wire = f'A3{param:02X}00{value:02X}'.encode() + conf + b'\r'
        v(f'dm-init-{param:02x}-{conf.decode()}', wire, checksum=False)

    # smart-mode lighting commands with confirmation codes
    i = 0
    for app in (0x38, 0x30, 0x5F):
        for ga in (0, 1, 10, 100, 255):
            conf = bytes([CONFIRMATION_CODES[i % len(CONFIRMATION_CODES)]])
            i += 1
            p = PointToMultipointPacket(sals=[LightingOnSAL(ga, app)])
            v(f'light-on-app{app:02x}-ga{ga}', client_wire(p, conf))
            p = PointToMultipointPacket(sals=[LightingOffSAL(ga, app)])
            v(f'light-off-app{app:02x}-ga{ga}', client_wire(p, conf))
    for code, duration in sorted(_LIGHT_RAMP_RATES.items()):
        p = PointToMultipointPacket(
            sals=[LightingRampSAL(44, 0x38, duration, 200)])
        v(f'light-ramp-{int(code):02x}', client_wire(p, b'g'))
    p = PointToMultipointPacket(sals=[LightingTerminateRampSAL(7, 0x38)])
    v('light-terminate', client_wire(p, b'z'))

    # multiple group addresses in one command (lighting_group_on semantics)
    p = PointToMultipointPacket(
        sals=[LightingOnSAL(g, 0x38) for g in (1, 2, 3, 4, 5)])
    v('light-on-multi5', client_wire(p, b'm'))

    # status requests as sent by cmqttd
    for app in (0x30, 0x38, 0x5F):
        for block in range(0, 256, 32):
            p = PointToMultipointPacket(sals=[StatusRequestSAL(
                level_request=True, group_address=block,
                child_application=app)])
            v(f'statusreq-app{app:02x}-b{block}', client_wire(p, b'h'))

    # PP identify / recall as sent by the interrogator
    for attr in (0x01, 0x02, 0x04):
        p = PointToPointPacket(unit_address=0x10,
                               cals=[IdentifyCAL(attr)])
        v(f'pp-identify-{attr:02x}', client_wire(p, b'i'))
    p = PointToPointPacket(unit_address=0x10, cals=[RecallCAL(0xFA, 44)])
    v('pp-recall-fa', client_wire(p, b'j'))
    # interrogator-style PP frame: flags 0x46 (priority class 3), no checksum
    v('pp-identify-interrogator-style', b'\\4610002101h\r', checksum=False,
      note='UnitInterrogator sends flags 0x46 and no checksum')

    # clock update (timesync) to network
    from datetime import datetime
    p = PointToMultipointPacket(
        sals=clock_update_sal(datetime(2026, 7, 20, 9, 8, 7)))
    v('clock-datetime', client_wire(p, b'k'))

    # no confirmation code at all
    p = PointToMultipointPacket(sals=[LightingOnSAL(1, 0x38)])
    v('light-on-noconf', client_wire(p, None))

    # invalid confirmation code (strict -> invalid packet)
    p = PointToMultipointPacket(sals=[LightingOnSAL(1, 0x38)])
    v('bad-conf-code-strict', client_wire(p, b'a'),
      note='confirmation char outside g..z: invalid in strict mode')
    v('bad-conf-code-lenient', client_wire(p, b'a'), strict=False,
      expect_reencodable=True,
      note='non-strict: warn, decode anyway, confirmation=a')
    return vecs


# ---------------------------------------------------------------------------
# suite: encode
# ---------------------------------------------------------------------------

def gen_encode():
    vecs = []
    P = 'en'

    def emit(slug, obj, pjson, packet_level=True):
        rec = {'id': _vid(P, slug), 'packet': pjson,
               'expect_encode_hex': obj.encode().hex()}
        if packet_level:
            rec['expect_encode_packet'] = \
                obj.encode_packet().decode('latin-1')
        vecs.append(rec)

    # specials
    emit('reset', ResetPacket(), {'type': 'reset'})
    emit('smart-connect', SmartConnectShortcutPacket(),
         {'type': 'smart_connect'})
    for success in (True, False):
        cp = ConfirmationPacket(b'h', success)
        emit(f'confirm-{success}', cp,
             {'type': 'confirmation', 'code': 'h', 'success': success})

    # DM packets (both checksum settings)
    for cs in (False, True):
        for (param, value) in [(0x21, 0xFF), (0x22, 0xFF), (0x42, 0x0E),
                               (0x30, 0x79), (0x00, 0x00), (0xFF, 0xFF)]:
            p = DeviceManagementPacket(checksum=cs, parameter=param,
                                       value=value)
            emit(f'dm-{param:02x}-{value:02x}-cs{int(cs)}', p,
                 packet_to_json(p))

    # PM packets: sweep sal types
    def pm(sals, checksum=True):
        return PointToMultipointPacket(checksum=checksum, sals=sals)

    for app in (0x30, 0x38, 0x4A, 0x5F):
        for ga in (0, 1, 100, 255):
            p = pm([LightingOnSAL(ga, app)])
            emit(f'pm-on-{app:02x}-{ga}', p, packet_to_json(p))
            p = pm([LightingOffSAL(ga, app)])
            emit(f'pm-off-{app:02x}-{ga}', p, packet_to_json(p))
    for code, duration in sorted(_LIGHT_RAMP_RATES.items()):
        for level in (0, 128, 255):
            p = pm([LightingRampSAL(5, 0x38, duration, level)])
            emit(f'pm-ramp-{int(code):02x}-{level}', p, packet_to_json(p))
    # ramp duration snapping: non-exact durations snap up to the next rate
    for dur in (1, 2, 3, 5, 7, 10, 15, 25, 35, 50, 75, 100, 150, 250,
                350, 500, 700, 1000, 1019, 1021, 5000, 100000):
        p = pm([LightingRampSAL(5, 0x38, dur, 128)])
        emit(f'pm-ramp-snap-{dur}', p, packet_to_json(p))

    from datetime import datetime
    for (h, m, s) in [(0, 0, 0), (23, 59, 59), (11, 22, 33)]:
        p = pm([ClockUpdateSAL(time(h, m, s))])
        emit(f'pm-clock-t{h:02}{m:02}{s:02}', p, packet_to_json(p))
    # dates across all weekdays (weekday byte: Monday=0)
    for d in (date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22),
              date(2026, 7, 23), date(2026, 7, 24), date(2026, 7, 25),
              date(2026, 7, 26), date(2000, 1, 1), date(2099, 12, 31),
              date(2024, 2, 29)):
        p = pm([ClockUpdateSAL(d)])
        emit(f'pm-clock-d{d.isoformat()}', p, packet_to_json(p))
    p = pm(list(clock_update_sal(datetime(2026, 7, 20, 10, 20, 30))))
    emit('pm-clock-datetime', p, packet_to_json(p))
    p = pm([ClockRequestSAL()])
    emit('pm-clock-request', p, packet_to_json(p))

    for tb in range(0, 256, 5):
        p = pm([TemperatureBroadcastSAL(20, tb / 4.0)])
        emit(f'pm-temp-{tb}', p, packet_to_json(p))

    for var, val in [(0, 0), (255, 255), (33, 66)]:
        p = pm([EnableSetNetworkVariableSAL(var, val)])
        emit(f'pm-enable-{var}-{val}', p, packet_to_json(p))

    for level in (False, True):
        for app in (0x30, 0x38, 0xFF):
            for block in range(0, 256, 32):
                p = pm([StatusRequestSAL(level, block, app)])
                emit(f'pm-sr-{int(level)}-{app:02x}-{block}', p,
                     packet_to_json(p))

    # PP packets
    for unit in (0, 1, 16, 255):
        p = PointToPointPacket(unit_address=unit, cals=[IdentifyCAL(0x01)])
        emit(f'pp-identify-u{unit}', p, packet_to_json(p))
    p = PointToPointPacket(unit_address=16, cals=[RecallCAL(0xFA, 44)])
    emit('pp-recall', p, packet_to_json(p))
    p = PointToPointPacket(unit_address=16,
                           cals=[ReplyCAL(0x01, b'PC_CNIED')])
    emit('pp-reply', p, packet_to_json(p))
    # ReplyCAL data clipping at 0x1e bytes
    long = bytes(range(0x40))
    p = PointToPointPacket(unit_address=16, cals=[ReplyCAL(0x02, long)])
    emit('pp-reply-clipped', p, packet_to_json(p))

    # standalone SAL encodes
    for app in (0x30, 0x38, 0x5F):
        s = LightingOnSAL(9, app)
        vecs.append({'id': _vid(P, f'sal-on-{app:02x}'),
                     'packet': {'type': 'sal', **sal_to_json(s)},
                     'expect_encode_hex': s.encode().hex()})
    s = LightingRampSAL(9, 0x38, 90, 77)
    vecs.append({'id': _vid(P, 'sal-ramp'),
                 'packet': {'type': 'sal', **sal_to_json(s)},
                 'expect_encode_hex': s.encode().hex()})
    s = StatusRequestSAL(False, 0x40, 0x38)
    vecs.append({'id': _vid(P, 'sal-sr-binary'),
                 'packet': {'type': 'sal', **sal_to_json(s)},
                 'expect_encode_hex': s.encode().hex()})

    # standalone CAL encodes
    c = IdentifyCAL(0x02)
    vecs.append({'id': _vid(P, 'cal-identify'),
                 'packet': {'type': 'cal', **cal_to_json(c)},
                 'expect_encode_hex': c.encode().hex()})
    c = RecallCAL(0x3E, 1)
    vecs.append({'id': _vid(P, 'cal-recall'),
                 'packet': {'type': 'cal', **cal_to_json(c)},
                 'expect_encode_hex': c.encode().hex()})
    c = ReplyCAL(0x01, b'KEYGL5  ')
    vecs.append({'id': _vid(P, 'cal-reply'),
                 'packet': {'type': 'cal', **cal_to_json(c)},
                 'expect_encode_hex': c.encode().hex()})
    c = ExtendedCAL(False, 0x38, 0, LevelStatusReport([0, 128, 255, None]))
    vecs.append({'id': _vid(P, 'cal-exstat-level'),
                 'packet': {'type': 'cal', **cal_to_json(c)},
                 'expect_encode_hex': c.encode().hex()})
    c = ExtendedCAL(True, 0x38, 32, BinaryStatusReport(
        [GroupState.ON, GroupState.OFF, GroupState.MISSING]))
    vecs.append({'id': _vid(P, 'cal-exstat-binary-pad'),
                 'packet': {'type': 'cal', **cal_to_json(c)},
                 'expect_encode_hex': c.encode().hex(),
                 'note': 'encode pads binary report to multiple of 4'})

    # standalone level report: exhaustive manchester encode of all 256 values
    for lvl in range(256):
        r = LevelStatusReport([lvl])
        vecs.append({'id': _vid(P, f'levelreport-{lvl:02x}'),
                     'packet': {'type': 'level_report', 'levels': [lvl]},
                     'expect_encode_hex': r.encode().hex()})
    r = LevelStatusReport([None])
    vecs.append({'id': _vid(P, 'levelreport-missing'),
                 'packet': {'type': 'level_report', 'levels': [None]},
                 'expect_encode_hex': r.encode().hex()})

    # binary report padding behaviours
    for n in (1, 2, 3, 4, 5, 88):
        states = [GroupState((i % 3) + 1) for i in range(n)]
        r = BinaryStatusReport(states)
        vecs.append({'id': _vid(P, f'binreport-{n}'),
                     'packet': {'type': 'binary_report',
                                'group_states': [int(s) for s in states]},
                     'expect_encode_hex': r.encode().hex()})
    return vecs


# ---------------------------------------------------------------------------
# suite: checksum + ramp rates
# ---------------------------------------------------------------------------

def gen_checksum():
    vecs = []
    P = 'ck'
    samples = [b'', b'\x00', b'\xff', b'\x05\x38\x00\x79\x01',
               b'\x00\x00\x00\x00', b'\xff\xff\xff\xff',
               bytes(range(256)), b'\x05\xff\x00\x73\x07\x38\x00',
               b'\x80' * 100]
    for i in range(256):
        samples.append(bytes([i]))
    for i, data in enumerate(samples):
        vecs.append({'id': _vid(P, f's{i}'), 'data_hex': data.hex(),
                     'expect_checksum': cbus_checksum(data)})
    return vecs


def gen_ramp_rates():
    vecs = []
    P = 'rr'
    for d in list(range(0, 1025)) + [1500, 5000, 100000]:
        vecs.append({'id': _vid(P, f'd{d}'), 'kind': 'duration_to_rate',
                     'in': d, 'expect': int(duration_to_ramp_rate(d))})
    for code in sorted(_LIGHT_RAMP_RATES):
        vecs.append({'id': _vid(P, f'c{int(code):02x}'),
                     'kind': 'rate_to_duration', 'in': int(code),
                     'expect': ramp_rate_to_duration(code)})
    return vecs


# ---------------------------------------------------------------------------
# suite: mqtt topics
# ---------------------------------------------------------------------------

def gen_mqtt_topics():
    vecs = []
    P = 'mt'
    combos = [(ga, 0x38) for ga in range(256)]
    for app in range(0x30, 0x60):
        for ga in (0, 1, 9, 10, 99, 100, 255):
            if app == 0x38:
                continue
            combos.append((ga, app))
    for ga, app in combos:
        vecs.append({
            'id': _vid(P, f'a{app:02x}-g{ga}'),
            'kind': 'format',
            'group_addr': ga, 'app_addr': app,
            'expect_ga_string_padded': ga_string(ga, app, True),
            'expect_ga_string_unpadded': ga_string(ga, app, False),
            'expect_set_topic': set_topic(ga, app),
            'expect_state_topic': state_topic(ga, app),
            'expect_conf_topic': conf_topic(ga, app),
            'expect_bin_sensor_state_topic': bin_sensor_state_topic(ga, app),
            'expect_bin_sensor_conf_topic': bin_sensor_conf_topic(ga, app),
        })
    # topic parsing vectors (set-topic -> (group, app))
    parse_cases = ['homeassistant/light/cbus_0/set',
                   'homeassistant/light/cbus_1/set',
                   'homeassistant/light/cbus_255/set',
                   'homeassistant/light/cbus_048_011/set',
                   'homeassistant/light/cbus_095_255/set',
                   'homeassistant/light/cbus_56_001/set',
                   'homeassistant/light/cbus_10/state',
                   'homeassistant/light/cbus_10/set']
    for t in parse_cases:
        rec = {'id': _vid(P, 'parse'), 'kind': 'parse', 'topic': t}
        try:
            g, a = get_topic_group_address(t)
            rec['expect_group'] = g
            rec['expect_app'] = int(a)
        except (ValueError, KeyError):
            rec['expect_error'] = True
        vecs.append(rec)
    for t in ['homeassistant/switch/cbus_1/set',
              'homeassistant/light/cbus_999/set',
              'homeassistant/light/cbus_xx/set']:
        rec = {'id': _vid(P, 'parse-err'), 'kind': 'parse', 'topic': t}
        try:
            g, a = get_topic_group_address(t)
            rec['expect_group'] = g
            rec['expect_app'] = int(a)
        except (ValueError, KeyError):
            rec['expect_error'] = True
        vecs.append(rec)
    return vecs


# ---------------------------------------------------------------------------
# suite: HA discovery payloads (exercises the real MqttClient code)
# ---------------------------------------------------------------------------

class _RecordingClient:
    def __init__(self):
        self.published = []
        self.subscribed = []

    async def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))

    async def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))


async def _collect_publishes(fn):
    rec = _RecordingClient()
    mc = MqttClient.__new__(MqttClient)  # skip __init__ network setup
    mc._client = rec
    mc.groupDB = {}
    fn(mc)
    await asyncio.sleep(0.05)
    return rec


def gen_ha_discovery():
    vecs = []
    P = 'ha'
    labels = {0x38: ('Lighting', {1: 'Kitchen Bench', 10: 'Lounge'}),
              0x30: ('Lighting 48', {11: 'Deck'})}

    cases = [(ga, 0x38, None) for ga in range(256)]
    cases += [(1, 0x38, labels), (10, 0x38, labels), (11, 0x30, labels),
              (0, 0x30, None), (255, 0x5F, None), (100, 0x45, None)]

    for ga, app, lab in cases:
        rec = asyncio.get_event_loop().run_until_complete(
            _collect_publishes(lambda mc, ga=ga, app=app, lab=lab:
                               mc.publish_light(ga, app, lab)))
        pubs = {t: (json.loads(p), qos, retain)
                for (t, p, qos, retain) in rec.published}
        light_topic = conf_topic(ga, app)
        sensor_topic = bin_sensor_conf_topic(ga, app)
        vecs.append({
            'id': _vid(P, f'a{app:02x}-g{ga}' + ('-lab' if lab else '')),
            'group_addr': ga, 'app_addr': app,
            'labels': ({str(k): [v[0], {str(g): n for g, n in v[1].items()}]
                        for k, v in lab.items()} if lab else None),
            'expect_subscribe': rec.subscribed[0][0],
            'expect_subscribe_qos': rec.subscribed[0][1],
            'expect_light_config_topic': light_topic,
            'expect_light_config': pubs[light_topic][0],
            'expect_sensor_config_topic': sensor_topic,
            'expect_sensor_config': pubs[sensor_topic][0],
            'expect_qos': 1, 'expect_retain': True,
        })

    # publish_all_lights meta config
    rec = asyncio.get_event_loop().run_until_complete(
        _collect_publishes(lambda mc: mc.publish_all_lights({})))
    (t, payload, qos, retain) = rec.published[0]
    vecs.append({'id': _vid(P, 'meta-config'), 'meta': True,
                 'expect_topic': t, 'expect_config': json.loads(payload),
                 'expect_qos': qos, 'expect_retain': retain})
    return vecs


# ---------------------------------------------------------------------------
# behavioral expectations (fixtures)
# ---------------------------------------------------------------------------

def gen_behavioral_expectations():
    # PCI init sequence. NOTE: the deployed (production) daemon sends the
    # DM frames withOUT confirmation chars — the repo Python (which this
    # generator runs against) requested confirmations, which was proven
    # wrong against the real CNI. conf is False for all init frames.
    init = [
        {'payload': '~', 'conf': False},
        {'payload': '~', 'conf': False},
        {'payload': '~', 'conf': False},
        {'payload': '|', 'conf': False},
        {'payload': 'A32100FF', 'conf': False},
        {'payload': 'A32200FF', 'conf': False},
        {'payload': 'A342000E', 'conf': False},
        {'payload': 'A3300079', 'conf': False},
    ]
    # sanity: DM packets encode to those exact strings
    for (param, value), expect in [((0x21, 0xFF), 'A32100FF'),
                                   ((0x22, 0xFF), 'A32200FF'),
                                   ((0x42, 0x0E), 'A342000E'),
                                   ((0x30, 0x79), 'A3300079')]:
        got = DeviceManagementPacket(
            checksum=False, parameter=param,
            value=value).encode_packet().decode()
        assert got == expect, (got, expect)

    # every status-request payload cmqttd may send (48 apps x 8 blocks)
    status_requests = {}
    for app in range(0x30, 0x60):
        for block in range(0, 256, 32):
            p = PointToMultipointPacket(sals=[StatusRequestSAL(
                level_request=True, group_address=block,
                child_application=app)])
            status_requests[f'{app:02x}:{block:02x}'] = \
                p.encode_packet().decode()

    def pm_wire(sals, source):
        p = PointToMultipointPacket(sals=sals)
        p.source_address = source
        return (p.encode_packet() + b'\r\n').decode()

    def pp_wire(p, source):
        p.source_address = source
        return (p.encode_packet() + b'\r\n').decode()

    def cmd_payload(sals):
        p = PointToMultipointPacket(sals=sals)
        return p.encode_packet().decode()

    # The exact wire sweep for fixtures/project.xml under the deployed
    # configured-sweep behaviour: configured apps ascending (48 then 56),
    # one block (0x00) each, binary status request before level.
    configured_sweep = [
        '05FF007A300052',
        '05FF007307300052',
        '05FF007A38004A',
        '05FF00730738004A',
    ]

    expectations = {
        'init_frames': init,
        'status_requests': status_requests,
        'configured_sweep': configured_sweep,
        'inject_lighting_on': {
            'wire': pm_wire([LightingOnSAL(10, 0x38)], 5),
            'state_topic': state_topic(10, 0x38),
            'state_payload': {'state': 'ON', 'brightness': 255,
                              'transition': 0, 'cbus_source_addr': 5},
            'sensor_topic': bin_sensor_state_topic(10, 0x38),
            'sensor_payload': 'ON',
        },
        'inject_lighting_ramp': {
            'wire': pm_wire([LightingRampSAL(11, 0x38, 12, 128)], 7),
            'state_topic': state_topic(11, 0x38),
            'state_payload': {'state': 'ON', 'brightness': 128,
                              'transition': 12, 'cbus_source_addr': 7},
            'sensor_topic': bin_sensor_state_topic(11, 0x38),
            'sensor_payload': 'ON',
        },
        'inject_clock_request': {
            'wire': pm_wire([ClockRequestSAL()], 20),
            'expect_app_hex': 'DF',
        },
        'inject_level_report': {
            'wire': pp_wire(
                PointToPointPacket(
                    unit_address=0x10,
                    cals=[ExtendedCAL(
                        False, 0x38, 0,
                        LevelStatusReport([None, 255, 0, 128]))]),
                0x99),
            'expect_states': [
                {'topic': state_topic(1, 0x38),
                 'payload': {'state': 'ON', 'brightness': 255,
                             'transition': 0, 'cbus_source_addr': 0}},
                {'topic': state_topic(2, 0x38),
                 'payload': {'state': 'OFF', 'brightness': 0,
                             'transition': 0, 'cbus_source_addr': 0}},
                {'topic': state_topic(3, 0x38),
                 'payload': {'state': 'ON', 'brightness': 128,
                             'transition': 0, 'cbus_source_addr': 0}},
            ],
        },
        'mqtt_cmd_off_default_app': {
            'topic': set_topic(10, 0x38),
            'payload': {'state': 'OFF'},
            'expect_pci_payload': cmd_payload([LightingOffSAL(10, 0x38)]),
            'echo_state_topic': state_topic(10, 0x38),
            'echo_state_payload': {'state': 'OFF', 'brightness': 0,
                                   'transition': 0,
                                   'cbus_source_addr': None},
        },
        'mqtt_cmd_on_alt_app': {
            'topic': set_topic(11, 0x30),
            'payload': {'state': 'ON'},
            'expect_pci_payload': cmd_payload([LightingOnSAL(11, 0x30)]),
            'echo_state_topic': state_topic(11, 0x30),
            'echo_state_payload': {'state': 'ON', 'brightness': 255,
                                   'transition': 0,
                                   'cbus_source_addr': None},
        },
        'project_labels': {
            'app_56_groups': {'1': 'Kitchen Bench', '10': 'Lounge'},
            'app_48_groups': {'11': 'Deck'},
        },
    }

    # expected discovery configs for the fixture project's labelled groups
    labels = {0x38: ('Lighting', {1: 'Kitchen Bench', 10: 'Lounge'}),
              0x30: ('Lighting 48', {11: 'Deck'})}
    label_configs = []
    for app, (_, groups) in labels.items():
        for ga, name in groups.items():
            rec = asyncio.get_event_loop().run_until_complete(
                _collect_publishes(lambda mc, ga=ga, app=app:
                                   mc.publish_light(ga, app, labels)))
            pubs = {t: json.loads(p) for (t, p, _, _) in rec.published}
            label_configs.append({
                'group_addr': ga, 'app_addr': app, 'label': name,
                'config_topic': conf_topic(ga, app),
                'config': pubs[conf_topic(ga, app)],
            })
    expectations['label_configs'] = label_configs

    # meta config
    rec = asyncio.get_event_loop().run_until_complete(
        _collect_publishes(lambda mc: mc.publish_all_lights({})))
    (t, payload, qos, retain) = rec.published[0]
    expectations['meta_config'] = {'topic': t,
                                   'config': json.loads(payload)}

    # lazy discovery config published when an unlabelled group first appears
    rec = asyncio.get_event_loop().run_until_complete(
        _collect_publishes(lambda mc: mc.publish_light(2, 0x38, None)))
    pubs = {t: json.loads(p) for (t, p, _, _) in rec.published}
    expectations['lazy_config_ga2'] = {
        'topic': conf_topic(2, 0x38),
        'config': pubs[conf_topic(2, 0x38)],
    }
    return expectations


# ---------------------------------------------------------------------------
# fixture project.xml self-check
# ---------------------------------------------------------------------------

def check_fixture_project():
    from cbus.daemon.cmqttd import read_cbz_labels
    path = os.path.join(FIX_DIR, 'project.xml')
    with open(path, 'rb') as fh:
        labels = read_cbz_labels(fh, None)
    expect = {56: ('Lighting', {1: 'Kitchen Bench', 10: 'Lounge'}),
              48: ('Lighting 48', {11: 'Deck'})}
    assert labels == expect, f'fixture project mismatch: {labels!r}'


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def write_jsonl(name, vecs):
    path = os.path.join(VEC_DIR, name)
    with open(path, 'w') as f:
        for v in vecs:
            f.write(json.dumps(v, sort_keys=True) + '\n')
    print(f'  {name}: {len(vecs)} vectors')
    return len(vecs)


def main():
    os.makedirs(VEC_DIR, exist_ok=True)
    os.makedirs(FIX_DIR, exist_ok=True)
    asyncio.set_event_loop(asyncio.new_event_loop())

    print('Generating golden vectors from working-tree Python...')
    total = 0
    total += write_jsonl('decode_from_pci.jsonl', gen_decode_from_pci())
    total += write_jsonl('decode_to_pci.jsonl', gen_decode_to_pci())
    total += write_jsonl('encode.jsonl', gen_encode())
    total += write_jsonl('checksum.jsonl', gen_checksum())
    total += write_jsonl('ramp_rates.jsonl', gen_ramp_rates())
    total += write_jsonl('mqtt_topics.jsonl', gen_mqtt_topics())
    total += write_jsonl('ha_discovery.jsonl', gen_ha_discovery())

    check_fixture_project()
    exp = gen_behavioral_expectations()
    path = os.path.join(FIX_DIR, 'behavioral_expectations.json')
    with open(path, 'w') as f:
        json.dump(exp, f, indent=1, sort_keys=True)
    print(f'  behavioral_expectations.json written')
    print(f'TOTAL: {total} vectors')


if __name__ == '__main__':
    main()
