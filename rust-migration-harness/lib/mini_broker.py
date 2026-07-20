"""Minimal MQTT 3.1.1 broker for the behavioral suite. Pure stdlib.

Supports exactly what cmqttd needs: CONNECT/CONNACK, PUBLISH QoS 0/1
(with PUBACK), a defensive QoS 2 handshake, SUBSCRIBE/SUBACK,
UNSUBSCRIBE/UNSUBACK, PINGREQ/PINGRESP and DISCONNECT. Records every
inbound PUBLISH and every subscription; can inject a PUBLISH to
subscribed clients (with topic-filter wildcard matching).

The Rust cmqttd MUST speak MQTT 3.1.1 (protocol level 4) -- the broker
rejects other protocol levels loudly so the failure mode is obvious.
"""
import asyncio
import time
from typing import Dict, List, Optional


def topic_matches(filt: str, topic: str) -> bool:
    fp = filt.split('/')
    tp = topic.split('/')
    for i, seg in enumerate(fp):
        if seg == '#':
            return True
        if i >= len(tp):
            return False
        if seg == '+':
            continue
        if seg != tp[i]:
            return False
    return len(fp) == len(tp)


class PublishRecord:
    def __init__(self, topic: str, payload: bytes, qos: int, retain: bool):
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.retain = retain
        self.ts = time.monotonic()

    def __repr__(self):
        return (f'Publish({self.topic!r}, {self.payload[:80]!r}, '
                f'qos={self.qos}, retain={self.retain})')


class _Client:
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.subscriptions: List[str] = []
        self.connected = False


def _encode_remaining(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _publish_packet(topic: str, payload: bytes, qos=0, retain=False) -> bytes:
    tb = topic.encode()
    var = len(tb).to_bytes(2, 'big') + tb
    if qos > 0:
        var += (1).to_bytes(2, 'big')  # fixed packet id for injections
    body = var + payload
    hdr = 0x30 | (qos << 1) | (0x01 if retain else 0)
    return bytes([hdr]) + _encode_remaining(len(body)) + body


class MiniBroker:
    def __init__(self, host='127.0.0.1', port=0):
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self.clients: List[_Client] = []
        self.publishes: List[PublishRecord] = []
        self.subscriptions: List[str] = []
        self.errors: List[str] = []
        self.retained: Dict[str, bytes] = {}

    @property
    def port(self) -> int:
        return self._server.sockets[0].getsockname()[1]

    async def start(self):
        self._server = await asyncio.start_server(
            self._on_client, self._host, self._port)

    async def stop(self):
        for c in self.clients:
            try:
                c.writer.close()
            except Exception:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    # ------------------------------------------------------------------
    async def _read_packet(self, reader):
        h = await reader.readexactly(1)
        mult, rem, i = 1, 0, 0
        while True:
            b = (await reader.readexactly(1))[0]
            rem += (b & 0x7f) * mult
            if not (b & 0x80):
                break
            mult *= 128
            i += 1
            if i > 3:
                raise ValueError('bad remaining length')
        body = await reader.readexactly(rem) if rem else b''
        return h[0], body

    async def _on_client(self, reader, writer):
        client = _Client(writer)
        self.clients.append(client)
        try:
            while True:
                ptype, body = await self._read_packet(reader)
                kind = ptype >> 4
                if kind == 1:  # CONNECT
                    # protocol name (len-prefixed) then level byte
                    nlen = int.from_bytes(body[0:2], 'big')
                    level = body[2 + nlen]
                    if level != 4:
                        self.errors.append(
                            f'client used MQTT protocol level {level}; '
                            f'this harness requires 3.1.1 (level 4)')
                        writer.write(bytes([0x20, 0x02, 0x00, 0x01]))
                        break
                    client.connected = True
                    writer.write(bytes([0x20, 0x02, 0x00, 0x00]))
                elif kind == 3:  # PUBLISH
                    qos = (ptype >> 1) & 0x03
                    retain = bool(ptype & 0x01)
                    tlen = int.from_bytes(body[0:2], 'big')
                    topic = body[2:2 + tlen].decode()
                    off = 2 + tlen
                    pid = None
                    if qos > 0:
                        pid = int.from_bytes(body[off:off + 2], 'big')
                        off += 2
                    payload = body[off:]
                    self.publishes.append(
                        PublishRecord(topic, payload, qos, retain))
                    if retain:
                        self.retained[topic] = payload
                    if qos == 1:
                        writer.write(b'\x40\x02' + pid.to_bytes(2, 'big'))
                    elif qos == 2:
                        writer.write(b'\x50\x02' + pid.to_bytes(2, 'big'))
                    # deliver to all matching subscribers (incl. sender),
                    # like a real broker; delivered at qos 0.
                    self._fanout(topic, payload)
                elif kind == 6:  # PUBREL (qos2 completion)
                    pid = int.from_bytes(body[0:2], 'big')
                    writer.write(b'\x70\x02' + pid.to_bytes(2, 'big'))
                elif kind == 8:  # SUBSCRIBE
                    pid = int.from_bytes(body[0:2], 'big')
                    off = 2
                    granted = bytearray()
                    while off < len(body):
                        tlen = int.from_bytes(body[off:off + 2], 'big')
                        topic = body[off + 2:off + 2 + tlen].decode()
                        rq = body[off + 2 + tlen]
                        off += 3 + tlen
                        client.subscriptions.append(topic)
                        self.subscriptions.append(topic)
                        granted.append(min(rq, 1))
                    writer.write(bytes([0x90]) +
                                 _encode_remaining(2 + len(granted)) +
                                 pid.to_bytes(2, 'big') + bytes(granted))
                elif kind == 10:  # UNSUBSCRIBE
                    pid = int.from_bytes(body[0:2], 'big')
                    writer.write(b'\xb0\x02' + pid.to_bytes(2, 'big'))
                elif kind == 12:  # PINGREQ
                    writer.write(b'\xd0\x00')
                elif kind == 14:  # DISCONNECT
                    break
                elif kind == 4:  # PUBACK for our injected qos1 (ignore)
                    pass
                else:
                    self.errors.append(f'unhandled MQTT packet type {kind}')
        except (asyncio.IncompleteReadError, ConnectionResetError,
                asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def _fanout(self, topic: str, payload: bytes):
        pkt = _publish_packet(topic, payload, qos=0, retain=False)
        for c in self.clients:
            if any(topic_matches(f, topic) for f in c.subscriptions):
                try:
                    c.writer.write(pkt)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    def inject(self, topic: str, payload: bytes):
        """Deliver a message to subscribed clients as if published by an
        external client (e.g. Home Assistant sending a /set command)."""
        self._fanout(topic, payload)

    # ---- query helpers ----------------------------------------------------
    def find_publishes(self, topic: str) -> List[PublishRecord]:
        return [p for p in self.publishes if p.topic == topic]

    def has_subscription(self, topic_filter: str) -> bool:
        return topic_filter in self.subscriptions
