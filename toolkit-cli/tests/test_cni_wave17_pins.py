"""Wave-17 offline pins for CNI discovery guards (P3.02 #29).

Narrow scope: guard semantics in cbus_toolkit.cni_discovery only, with
injected fakes (no sockets, hardware, subprocess, or psutil). Each pinned
guard phrase has zero prior references in tests/.
"""

import socket
from types import SimpleNamespace

import pytest

from cbus_toolkit.cni_discovery import (
    DISCOVERY_QUERY,
    _pin_discovery_interface,
    decode_discovery_reply,
    discover_cni,
    plan_host_cni_probes,
)

CNI2 = bytes.fromhex(
    "cb81000020e8f5528101000101810b00022711811d000101800100028c26"
)


def test_wave17_wiser_product_is_visible_by_default():
    raw = bytearray(CNI2)
    raw[12] = 3
    reply = decode_discovery_reply(bytes(raw))
    assert reply.product == "wiser"
    assert reply.visible_by_default is True
    assert reply.as_dict()["product"] == "wiser"


def test_wave17_interface_pin_conversion_index_and_ifnamsiz_guards():
    class Peer:
        def setsockopt(self, *_args):
            raise AssertionError("socket option must not be attempted")

        def getsockopt(self, *_args):
            raise AssertionError("readback must not be attempted")

    from cbus_toolkit.cni_discovery import _windows_interface_index

    with pytest.raises(OSError, match="conversion is unavailable"):
        _windows_interface_index("en0", api=object())

    with pytest.raises(OSError, match="index unavailable"):
        def _missing(_name):
            raise OSError("no such device")

        _pin_discovery_interface(
            Peer(), "en0", platform="darwin", if_nametoindex=_missing)

    for bad in (0, 2 ** 32, "42", None):
        with pytest.raises(OSError, match="outside the supported IPv4 range"):
            _pin_discovery_interface(
                Peer(), "en0", platform="darwin",
                if_nametoindex=lambda _name, _bad=bad: _bad)

    with pytest.raises(OSError, match="exceeds IFNAMSIZ"):
        _pin_discovery_interface(
            Peer(), "a" * 16, platform="linux",
            if_nametoindex=lambda _name: 5)


def _adapter(address, netmask, **kwargs):
    fields = {"family": socket.AF_INET, "address": address,
              "netmask": netmask, "broadcast": None, "ptp": None}
    fields.update(kwargs)
    return SimpleNamespace(**fields)


def test_wave17_host_inventory_no_ipv4_duplicate_and_empty_guards():
    addrs = {
        "good": [_adapter("192.0.2.10", "255.255.255.0")],
        "only6": [SimpleNamespace(family=socket.AF_INET6,
                                   address="fe80::1", netmask=None,
                                   broadcast=None, ptp=None)],
    }
    stats = {name: SimpleNamespace(isup=True) for name in addrs}
    plan = plan_host_cni_probes(net_if_addrs=lambda: addrs,
                                net_if_stats=lambda: stats)
    assert plan["probe_count"] == 1
    assert any(item["reason"] == "no_ipv4_address"
               for item in plan["skipped"])

    dup_addrs = {
        "eth0": [_adapter("192.0.2.10", "255.255.255.0")],
        "eth1": [_adapter("192.0.2.10", "255.255.255.0")],
    }
    dup_stats = {name: SimpleNamespace(isup=True) for name in dup_addrs}
    dup_plan = plan_host_cni_probes(net_if_addrs=lambda: dup_addrs,
                                    net_if_stats=lambda: dup_stats)
    assert dup_plan["probe_count"] == 1
    assert any(item["reason"] == "duplicate_route"
               for item in dup_plan["skipped"])

    down_addrs = {"down0": [_adapter("192.0.2.10", "255.255.255.0")]}
    down_stats = {"down0": SimpleNamespace(isup=False)}
    with pytest.raises(ValueError, match="No active broadcast"):
        plan_host_cni_probes(net_if_addrs=lambda: down_addrs,
                             net_if_stats=lambda: down_stats)


def test_wave17_short_send_never_claims_query_sent():
    class FakePeer:
        def __init__(self):
            self.closed = False

        def setsockopt(self, *_args):
            return None

        def bind(self, *_args):
            return None

        def getsockname(self):
            return ("127.0.0.1", 1234)

        def sendto(self, *_args):
            return len(DISCOVERY_QUERY) - 1

        def settimeout(self, *_args):
            return None

        def recvfrom(self, *_args):
            raise AssertionError("reply must not be awaited after short send")

        def close(self):
            self.closed = True

    peer = FakePeer()
    with pytest.raises(OSError, match="query bytes"):
        discover_cni(bind="127.0.0.1", listen_port=0,
                     destination="127.0.0.1", discovery_port=20050,
                     timeout=0.1,
                     socket_factory=lambda *_args: peer,
                     clock=lambda: 0.0)
    assert peer.closed is True
