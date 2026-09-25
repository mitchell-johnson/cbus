"""Bounded IPv4 UDP discovery for captured CNI2 and Wiser interfaces.

This protocol is separate from the ASCII PCI stream.  It sends the one exact
19-byte query retained from the original discovery client and strictly parses
the fixed 30-byte reply layout.  Opaque fields are preserved rather than
assigned unverified meanings.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
import time


DISCOVERY_PORT = 20_050
DISCOVERY_QUERY = bytes.fromhex("cb800000000000000101010b011d80010247ff")
DISCOVERY_REPLY_LENGTH = 30
MAX_DISCOVERY_DATAGRAMS = 4_096


@dataclass(frozen=True)
class CniDiscoveryReply:
    unknown1: bytes
    product_id: int
    service_port: int
    status: int
    trailer: bytes

    @property
    def product(self):
        return {1: "cni2", 2: "hidden", 3: "wiser"}.get(self.product_id, "unknown")

    @property
    def visible_by_default(self):
        return self.product_id != 2

    def as_dict(self):
        return {
            "unknown1_hex": self.unknown1.hex(),
            "product_id": self.product_id,
            "product": self.product,
            "service_port": self.service_port,
            "status": self.status,
            "trailer_hex": self.trailer.hex(),
            "visible_by_default": self.visible_by_default,
        }


def decode_discovery_reply(data):
    """Decode one exact fixed-layout reply without interpreting opaque fields."""
    if not isinstance(data, bytes):
        raise TypeError("CNI discovery reply must be bytes")
    if len(data) != DISCOVERY_REPLY_LENGTH:
        raise ValueError(
            f"CNI discovery reply must be exactly {DISCOVERY_REPLY_LENGTH} bytes, got {len(data)}"
        )
    if data[:4] != bytes.fromhex("cb810000"):
        raise ValueError("Invalid CNI discovery reply magic")
    fields = (
        (8, bytes.fromhex("81010001"), "product"),
        (13, bytes.fromhex("810b0002"), "service-port"),
        (19, bytes.fromhex("811d0001"), "status"),
        (24, bytes.fromhex("80010002"), "trailer"),
    )
    for offset, expected, name in fields:
        if data[offset:offset + len(expected)] != expected:
            raise ValueError(f"Invalid CNI discovery {name} field tag")
    return CniDiscoveryReply(
        unknown1=data[4:8],
        product_id=data[12],
        service_port=int.from_bytes(data[17:19], "big"),
        status=data[23],
        trailer=data[28:30],
    )


def _ipv4(value, label):
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a numeric IPv4 address") from error
    if not isinstance(address, ipaddress.IPv4Address):
        raise ValueError(f"{label} must be a numeric IPv4 address")
    return str(address)


def _port(value, label, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    lower = 0 if allow_zero else 1
    if not lower <= value <= 65_535:
        raise ValueError(f"{label} must be in {lower}..65535")
    return value


def discover_cni(*, bind="0.0.0.0", listen_port=DISCOVERY_PORT,
                 destination="255.255.255.255", discovery_port=DISCOVERY_PORT,
                 timeout=2.0, max_datagrams=256, include_hidden=False,
                 socket_factory=socket.socket, clock=time.monotonic):
    """Send one query and collect bounded replies through a monotonic deadline.

    The returned endpoint uses the UDP source address and the advertised TCP
    port.  A timeout completes the observation normally; zero replies never
    prove that an interface is absent.
    """
    bind = _ipv4(bind, "CNI discovery bind address")
    destination = _ipv4(destination, "CNI discovery destination")
    listen_port = _port(listen_port, "CNI discovery listen port", allow_zero=True)
    discovery_port = _port(discovery_port, "CNI discovery destination port")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 300:
        raise ValueError("CNI discovery timeout must be finite and in (0, 300]")
    if timeout != timeout or timeout in (float("inf"), float("-inf")):
        raise ValueError("CNI discovery timeout must be finite and in (0, 300]")
    if (isinstance(max_datagrams, bool) or not isinstance(max_datagrams, int)
            or not 1 <= max_datagrams <= MAX_DISCOVERY_DATAGRAMS):
        raise ValueError(
            f"CNI discovery max_datagrams must be in 1..={MAX_DISCOVERY_DATAGRAMS}"
        )
    if not isinstance(include_hidden, bool):
        raise ValueError("CNI discovery include_hidden must be a boolean")

    peer = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
    devices = []
    malformed = []
    seen = set()
    duplicates = hidden = received = 0
    complete = True
    try:
        peer.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        peer.bind((bind, listen_port))
        local_address, local_port = peer.getsockname()[:2]
        sent = peer.sendto(DISCOVERY_QUERY, (destination, discovery_port))
        if sent != len(DISCOVERY_QUERY):
            raise OSError(f"CNI discovery sent {sent} of {len(DISCOVERY_QUERY)} query bytes")
        deadline = clock() + float(timeout)
        while True:
            if received == max_datagrams:
                complete = False
                break
            remaining = deadline - clock()
            if remaining <= 0:
                break
            peer.settimeout(remaining)
            try:
                raw, source = peer.recvfrom(65_535)
            except (socket.timeout, TimeoutError):
                break
            received += 1
            source_address, source_port = source[:2]
            key = (source_address, source_port, raw)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            try:
                reply = decode_discovery_reply(raw)
            except (TypeError, ValueError) as error:
                malformed.append({
                    "source": f"{source_address}:{source_port}",
                    "raw_hex": raw.hex(),
                    "error": str(error),
                })
                continue
            if not include_hidden and not reply.visible_by_default:
                hidden += 1
                continue
            details = reply.as_dict()
            details["status_raw"] = details.pop("status")
            devices.append({
                "source_address": source_address,
                "source_port": source_port,
                "service_address": source_address,
                "service_port": reply.service_port,
                "endpoint": f"{source_address}:{reply.service_port}",
                **details,
                "raw_hex": raw.hex(),
            })
        devices.sort(key=lambda item: (
            ipaddress.IPv4Address(item["source_address"]), item["service_port"],
            item["product_id"], item["unknown1_hex"],
        ))
        malformed.sort(key=lambda item: (
            item["source"], item["raw_hex"], item["error"],
        ))
        return {
            "format": "cbus-cni-discovery-v1",
            "query_hex": DISCOVERY_QUERY.hex(),
            "query_sent_once": True,
            "listen": {"address": local_address, "port": local_port},
            "destination": {"address": destination, "port": discovery_port},
            "collection_complete": complete,
            "collection_ended": "deadline" if complete else "datagram_limit",
            "datagrams_received": received,
            "duplicates_ignored": duplicates,
            "hidden_ignored": hidden,
            "devices": devices,
            "malformed": malformed,
            "read_only": True,
            "tcp_connection_opened": False,
            "absence_proven": False,
            "scope": (
                "Captured fixed-layout IPv4 UDP discovery; no TCP reachability, ownership, "
                "identity authenticity or physical-network validation"
            ),
        }
    finally:
        peer.close()
