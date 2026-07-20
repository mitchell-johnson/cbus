"""mDNS discovery for ESP32 C-Bus bridge devices.

Uses zeroconf to discover ESP32 devices advertising the C-Bus service
on the local network. Falls back gracefully when zeroconf is not installed.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

CBUS_MDNS_SERVICE_TYPE = "_cbus._tcp.local."

try:
    from zeroconf import ServiceStateChange
    from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
    _ZEROCONF_AVAILABLE = True
except ImportError:
    _ZEROCONF_AVAILABLE = False


@dataclass
class DiscoveredDevice:
    name: str
    host: str
    port: int
    properties: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def manual(cls, host: str, port: int = 10001) -> "DiscoveredDevice":
        return cls(name=f"manual-{host}", host=host, port=port)

    def __str__(self):
        return f"{self.name} @ {self.host}:{self.port}"


class ESP32Discovery:
    """Discover ESP32 C-Bus bridge devices via mDNS."""

    def __init__(self, timeout: float = 5.0):
        self._timeout = timeout
        self._devices: List[DiscoveredDevice] = []

    async def discover(self) -> List[DiscoveredDevice]:
        if not _ZEROCONF_AVAILABLE:
            logger.warning(
                "zeroconf not installed, mDNS discovery unavailable. "
                "Install with: pip install zeroconf"
            )
            return []

        self._devices = []
        try:
            azc = AsyncZeroconf()
            browser = AsyncServiceBrowser(
                azc.zeroconf,
                CBUS_MDNS_SERVICE_TYPE,
                handlers=[self._on_service_state_change],
            )
            await asyncio.sleep(self._timeout)
            await browser.async_cancel()
            await azc.async_close()
        except Exception as e:
            logger.error("mDNS discovery failed: %s", e)

        logger.info("Discovered %d ESP32 C-Bus device(s)", len(self._devices))
        return list(self._devices)

    def _on_service_state_change(self, zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info:
                addresses = info.parsed_addresses()
                if addresses:
                    props = {}
                    if info.properties:
                        props = {
                            k.decode("utf-8", errors="replace"): v.decode(
                                "utf-8", errors="replace"
                            )
                            for k, v in info.properties.items()
                        }
                    device = DiscoveredDevice(
                        name=name.replace(f".{service_type}", ""),
                        host=addresses[0],
                        port=info.port or 10001,
                        properties=props,
                    )
                    self._devices.append(device)
                    logger.info("Discovered device: %s", device)
