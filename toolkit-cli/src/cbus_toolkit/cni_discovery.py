"""Bounded IPv4 UDP discovery for captured CNI2 and Wiser interfaces.

This protocol is separate from the ASCII PCI stream.  It sends the one exact
19-byte query retained from the original discovery client and strictly parses
the fixed 30-byte reply layout.  Opaque fields are preserved rather than
assigned unverified meanings.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import socket
import time


DISCOVERY_PORT = 20_050
DISCOVERY_QUERY = bytes.fromhex("cb800000000000000101010b011d80010247ff")
DISCOVERY_REPLY_LENGTH = 30
MAX_DISCOVERY_DATAGRAMS = 4_096
MAX_DISCOVERY_PROBES = 16
MAX_DISCOVERY_SCAN_SECONDS = 300
MAX_MALFORMED_RAW_PREFIX = 64
MAX_ENUMERATED_INTERFACES = 256


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


def _timeout(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value != value or value in (float("inf"), float("-inf"))
            or not 0 < value <= 300):
        raise ValueError("CNI discovery timeout must be finite and in (0, 300]")
    return float(value)


def _max_datagrams(value):
    if (isinstance(value, bool) or not isinstance(value, int)
            or not 1 <= value <= MAX_DISCOVERY_DATAGRAMS):
        raise ValueError(
            f"CNI discovery max_datagrams must be in 1..={MAX_DISCOVERY_DATAGRAMS}"
        )
    return value


def _probe(value):
    if not isinstance(value, str) or value.count("@") != 1:
        raise ValueError("CNI discovery probe must be BIND_IPV4@DESTINATION_IPV4")
    bind, destination = value.split("@")
    return (_ipv4(bind, "CNI discovery probe bind address"),
            _ipv4(destination, "CNI discovery probe destination"))


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
    timeout = _timeout(timeout)
    max_datagrams = _max_datagrams(max_datagrams)
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
        deadline = clock() + timeout
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
            key = (source_address, source_port, len(raw), hashlib.sha256(raw).digest())
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            try:
                reply = decode_discovery_reply(raw)
            except (TypeError, ValueError) as error:
                malformed.append({
                    "source": f"{source_address}:{source_port}",
                    "raw_hex": raw[:MAX_MALFORMED_RAW_PREFIX].hex(),
                    "raw_length": len(raw),
                    "raw_truncated": len(raw) > MAX_MALFORMED_RAW_PREFIX,
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


def validate_scan_cni(probes, *, listen_port=DISCOVERY_PORT,
                      discovery_port=DISCOVERY_PORT, timeout=2.0,
                      max_datagrams=256, include_hidden=False):
    """Validate every route and scan bound without opening a socket."""
    if not isinstance(probes, (list, tuple)) or not 1 <= len(probes) <= MAX_DISCOVERY_PROBES:
        raise ValueError(f"CNI discovery requires 1..={MAX_DISCOVERY_PROBES} probes")
    routes = tuple(_probe(value) for value in probes)
    if len(set(routes)) != len(routes):
        raise ValueError("CNI discovery probes must be unique")
    listen_port = _port(listen_port, "CNI discovery listen port", allow_zero=True)
    discovery_port = _port(discovery_port, "CNI discovery destination port")
    timeout = _timeout(timeout)
    max_datagrams = _max_datagrams(max_datagrams)
    if not isinstance(include_hidden, bool):
        raise ValueError("CNI discovery include_hidden must be a boolean")
    if timeout * len(routes) > MAX_DISCOVERY_SCAN_SECONDS:
        raise ValueError(
            f"CNI discovery configured scan window must be <= {MAX_DISCOVERY_SCAN_SECONDS} seconds"
        )
    return routes


def scan_cni(probes, *, listen_port=DISCOVERY_PORT,
             discovery_port=DISCOVERY_PORT, timeout=2.0, max_datagrams=256,
             include_hidden=False, discover=discover_cni):
    """Run an explicit bounded sequence of independent CNI/Wiser UDP probes.

    Every route is validated before the first socket opens. Each successful
    probe uses the captured single-query contract; failures in one local
    adapter do not erase observations from later probes. No result proves that
    a device is absent or that its advertised TCP service is reachable.
    """
    routes = validate_scan_cni(
        probes, listen_port=listen_port, discovery_port=discovery_port,
        timeout=timeout, max_datagrams=max_datagrams,
        include_hidden=include_hidden,
    )

    observations = []
    for bind, destination in routes:
        route = {"bind": bind, "destination": destination}
        try:
            result = discover(
                bind=bind, listen_port=listen_port, destination=destination,
                discovery_port=discovery_port, timeout=timeout,
                max_datagrams=max_datagrams, include_hidden=include_hidden,
            )
        except OSError as error:
            observations.append({
                "route": route,
                "outcome": "transport_error",
                "query_sent_once": None,
                "error": str(error),
                "observation": None,
            })
            continue
        if not result["collection_complete"]:
            outcome = "datagram_limit"
        elif result["devices"]:
            outcome = "devices_observed"
        elif result["hidden_ignored"] and result["malformed"]:
            outcome = "filtered_replies_by_deadline"
        elif result["hidden_ignored"]:
            outcome = "hidden_replies_by_deadline"
        elif result["malformed"]:
            outcome = "no_valid_reply_by_deadline"
        else:
            outcome = "no_reply_by_deadline"
        observations.append({
            "route": route,
            "outcome": outcome,
            "query_sent_once": True,
            "error": None,
            "observation": result,
        })
    return {
        "format": "cbus-cni-multi-discovery-v1",
        "query_hex": DISCOVERY_QUERY.hex(),
        "probes": observations,
        "probe_count": len(observations),
        "scan_complete": all(probe["observation"] is not None
                             and probe["observation"]["collection_complete"]
                             for probe in observations),
        "absence_proven": False,
        "ownership_checked": False,
        "tcp_connection_opened": False,
    }


def plan_host_cni_probes(*, interfaces=None, net_if_addrs=None, net_if_stats=None):
    """Derive directed-broadcast probes from one host adapter observation.

    ``psutil`` is optional because the base CLI also supports explicit routes.
    Injection keeps the route selection testable without querying a host or
    sending discovery traffic. Interface status and addresses are separate,
    non-atomic OS observations; the result is never an absence proof.
    """
    if interfaces is not None:
        if (not isinstance(interfaces, (tuple, list)) or not interfaces
                or any(type(name) is not str or not name for name in interfaces)
                or len(set(interfaces)) != len(interfaces)):
            raise ValueError("CNI adapter names must be a nonempty unique sequence")
        requested = tuple(interfaces)
    else:
        requested = None
    if (net_if_addrs is None) != (net_if_stats is None):
        raise ValueError("CNI adapter address and status providers must be supplied together")
    source = "injected_adapter_providers"
    if net_if_addrs is None:
        try:
            import psutil
        except ImportError as error:
            raise RuntimeError(
                "Automatic CNI adapter discovery requires cbus-toolkit-cli[network]"
            ) from error
        net_if_addrs, net_if_stats = psutil.net_if_addrs, psutil.net_if_stats
        source = "psutil.net_if_addrs+net_if_stats"
    addresses, statuses = net_if_addrs(), net_if_stats()
    if not isinstance(addresses, dict) or not isinstance(statuses, dict):
        raise ValueError("CNI adapter providers must return dictionaries")
    if len(addresses) > MAX_ENUMERATED_INTERFACES:
        raise ValueError("CNI host adapter inventory exceeds its bound")
    if requested is not None:
        missing = set(requested) - set(addresses)
        if missing:
            raise ValueError("CNI requested adapter is absent: " + sorted(missing)[0])
    names = sorted(addresses) if requested is None else sorted(requested)
    selected, skipped, seen = [], [], set()
    for name in names:
        if type(name) is not str or not name:
            raise ValueError("CNI adapter inventory contains an invalid name")
        status = statuses.get(name)
        if status is None or not getattr(status, "isup", False):
            skipped.append({"interface": name, "reason": "down_or_status_unavailable"})
            continue
        ipv4_found = False
        for address in addresses[name]:
            if getattr(address, "family", None) != socket.AF_INET:
                continue
            ipv4_found = True
            try:
                bind = ipaddress.IPv4Address(address.address)
                netmask = ipaddress.IPv4Address(address.netmask)
                network = ipaddress.IPv4Network((str(bind), str(netmask)), strict=False)
            except (ValueError, TypeError, AttributeError):
                skipped.append({"interface": name, "reason": "invalid_ipv4_or_netmask"})
                continue
            if (bind.is_loopback or bind.is_multicast or bind.is_unspecified
                    or getattr(address, "ptp", None)):
                skipped.append({"interface": name, "address": str(bind),
                                "reason": "loopback_multicast_or_point_to_point"})
                continue
            if (not 1 <= network.prefixlen <= 30 or bind == network.network_address
                    or bind == network.broadcast_address):
                skipped.append({"interface": name, "address": str(bind),
                                "reason": "no_usable_directed_broadcast"})
                continue
            destination = network.broadcast_address
            os_broadcast = getattr(address, "broadcast", None)
            if os_broadcast:
                try:
                    reported = ipaddress.IPv4Address(os_broadcast)
                except (ValueError, TypeError):
                    skipped.append({"interface": name, "address": str(bind),
                                    "reason": "invalid_reported_broadcast"})
                    continue
                if reported not in (destination, ipaddress.IPv4Address("255.255.255.255")):
                    skipped.append({"interface": name, "address": str(bind),
                                    "reason": "reported_broadcast_mismatch"})
                    continue
            route = (str(bind), str(destination))
            if route in seen:
                skipped.append({"interface": name, "address": str(bind),
                                "reason": "duplicate_route"})
                continue
            seen.add(route)
            selected.append({"interface": name, "bind": route[0],
                             "destination": route[1], "netmask": str(netmask),
                             "prefix_length": network.prefixlen,
                             "reported_broadcast": os_broadcast})
        if not ipv4_found:
            skipped.append({"interface": name, "reason": "no_ipv4_address"})
    selected.sort(key=lambda item: (item["interface"], ipaddress.IPv4Address(item["bind"])))
    if requested is not None:
        missing_routes = set(requested) - {item["interface"] for item in selected}
        if missing_routes:
            raise ValueError("CNI requested adapter has no usable broadcast route: "
                             + sorted(missing_routes)[0])
    if not selected:
        raise ValueError("No active broadcast-capable IPv4 adapter was found")
    if len(selected) > MAX_DISCOVERY_PROBES:
        raise ValueError(f"CNI automatic scan exceeds {MAX_DISCOVERY_PROBES} route limit")
    return {
        "source": source,
        "requested_interfaces": None if requested is None else list(requested),
        "selected": selected,
        "skipped": skipped,
        "probe_count": len(selected),
        "network_state_snapshot_atomic": False,
        "egress_interface_verified": False,
        "absence_proven": False,
    }


def scan_host_cni(*, interfaces=None, net_if_addrs=None, net_if_stats=None,
                  discover=discover_cni, **scan_options):
    """Scan every admitted host broadcast route; retain per-route outcomes."""
    plan = plan_host_cni_probes(
        interfaces=interfaces, net_if_addrs=net_if_addrs, net_if_stats=net_if_stats,
    )
    report = scan_cni(
        [item["bind"] + "@" + item["destination"] for item in plan["selected"]],
        discover=discover, **scan_options,
    )
    for probe, adapter in zip(report["probes"], plan["selected"], strict=True):
        probe["adapter"] = adapter
    report["automatic_adapter_enumeration"] = True
    report["adapter_enumeration"] = plan
    report["egress_interface_verified"] = False
    return report
