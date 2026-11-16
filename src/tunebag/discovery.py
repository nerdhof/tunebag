"""LAN discovery: advertise + browse. Tests inject FakeLanDiscovery."""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_tunebag._tcp.local."
DISCOVERY_REFRESH_SECONDS = 60.0


@dataclass(frozen=True)
class LanAdvertisement:
    """mDNS-sized ad: name, fingerprint, Locator — not the full public key."""

    name: str
    fingerprint: str
    locator: str
    pairing: bool = False

    @property
    def short_code(self) -> str:
        """Alias: fingerprint is the discovery label (not a pairing secret)."""
        return self.fingerprint


class LanDiscovery(Protocol):
    def advertise(self, advertisement: LanAdvertisement) -> None: ...

    def withdraw(self) -> None: ...

    def browse(self) -> list[LanAdvertisement]: ...


class NullLanDiscovery:
    """No-op discovery when mDNS is unavailable or not injected."""

    def advertise(self, advertisement: LanAdvertisement) -> None:
        return None

    def withdraw(self) -> None:
        return None

    def browse(self) -> list[LanAdvertisement]:
        return []


@dataclass
class FakeLanDiscovery:
    """Shared in-memory LAN for agent tests (no multicast)."""

    _ads: dict[str, LanAdvertisement] = field(default_factory=dict)
    _pairing: dict[str, Callable[[], dict[str, Any]]] = field(default_factory=dict)
    _agents: dict[str, Any] = field(default_factory=dict)
    browse_calls: int = 0

    def advertise(self, advertisement: LanAdvertisement) -> None:
        self._ads[advertisement.locator] = advertisement

    def withdraw(self) -> None:
        return None

    def browse(self) -> list[LanAdvertisement]:
        self.browse_calls += 1
        return list(self._ads.values())

    def publish(self, agent: Any, *, locator: str | None = None) -> str:
        """Register an in-process agent as an advertisement on this fake LAN."""
        loc = locator or agent.base_url or f"inproc://{agent.device_id}"
        payload = agent.pairing_payload()
        pairing_open = bool(getattr(agent, "pairing_session_open", lambda: False)())
        ad = LanAdvertisement(
            name=agent.name,
            fingerprint=agent.fingerprint(),
            locator=loc,
            pairing=pairing_open,
        )
        self._ads[loc] = ad
        self._pairing[loc] = lambda: {**payload, "url": loc}
        self._agents[loc] = agent
        return loc

    def pairing_payload(self, locator: str) -> dict[str, Any]:
        fetcher = self._pairing.get(locator)
        if fetcher is None:
            raise ValueError(f"no pairing payload for locator {locator}")
        return fetcher()

    def agent_at(self, locator: str) -> Any | None:
        return self._agents.get(locator)

    def clear(self) -> None:
        """Drop all advertisements (test helper for empty-LAN scenarios)."""
        self._ads.clear()
        self._pairing.clear()
        self._agents.clear()


class MdnsLanDiscovery:
    """DNS-SD advertise + browse via zeroconf (same-LAN multicast only)."""

    def __init__(self) -> None:
        from zeroconf import Zeroconf

        self._zc = Zeroconf()
        self._info = None
        self._browser = None
        self._seen: dict[str, LanAdvertisement] = {}
        self._local_locator: str | None = None

    def advertise(self, advertisement: LanAdvertisement) -> None:
        from zeroconf import ServiceInfo

        self._local_locator = advertisement.locator.rstrip("/")
        parsed = urlparse(advertisement.locator)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addrs: list[bytes] = []
        try:
            for family, _, _, _, sockaddr in socket.getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            ):
                if family == socket.AF_INET:
                    addrs.append(socket.inet_aton(sockaddr[0]))
        except OSError:
            logger.warning("mDNS advertise: could not resolve %s", host)
        if not addrs:
            addrs = [socket.inet_aton("127.0.0.1")]
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in advertisement.name)
        props = {
            b"name": advertisement.name.encode("utf-8"),
            b"fingerprint": advertisement.fingerprint.encode("utf-8"),
            # Older browsers may still read short_code as the discovery label.
            b"short_code": advertisement.fingerprint.encode("utf-8"),
            b"locator": advertisement.locator.encode("utf-8"),
            b"pairing": b"1" if advertisement.pairing else b"0",
        }
        info = ServiceInfo(
            SERVICE_TYPE,
            f"{safe}.{SERVICE_TYPE}",
            addresses=addrs,
            port=port,
            properties=props,
            server=f"{safe}.local.",
        )
        # Re-advertise (e.g. pairing flag flip) must replace, not double-register.
        if self._info is not None:
            try:
                self._zc.update_service(info)
                self._info = info
                return
            except Exception:
                logger.debug("mDNS update_service failed; re-registering", exc_info=True)
                try:
                    self._zc.unregister_service(self._info)
                except Exception:
                    logger.debug("mDNS unregister before re-advertise failed", exc_info=True)
                self._info = None
        self._info = info
        self._zc.register_service(info)

    def withdraw(self) -> None:
        if self._browser is not None:
            self._browser.cancel()
            self._browser = None
        if self._info is not None:
            try:
                self._zc.unregister_service(self._info)
            except Exception:
                logger.debug("mDNS unregister failed", exc_info=True)
            self._info = None
        self._zc.close()

    def browse(self) -> list[LanAdvertisement]:
        from zeroconf import ServiceBrowser, ServiceListener

        discovery = self

        class _Listener(ServiceListener):
            def add_service(self, zc: Any, type_: str, name: str) -> None:
                info = zc.get_service_info(type_, name)
                if info is None:
                    return
                props = {
                    (k.decode() if isinstance(k, bytes) else str(k)): (
                        v.decode() if isinstance(v, bytes) else str(v)
                    )
                    for k, v in (info.properties or {}).items()
                }
                locator = props.get("locator")
                if not locator and info.addresses and info.port:
                    ip = socket.inet_ntoa(info.addresses[0])
                    locator = f"http://{ip}:{info.port}"
                if not locator:
                    return
                if (
                    discovery._local_locator
                    and locator.rstrip("/") == discovery._local_locator
                ):
                    return
                fingerprint = props.get("fingerprint") or props.get("short_code") or ""
                discovery._seen[locator] = LanAdvertisement(
                    name=props.get("name") or name.split(".")[0],
                    fingerprint=fingerprint,
                    locator=locator,
                    pairing=props.get("pairing") == "1",
                )

            def remove_service(self, zc: Any, type_: str, name: str) -> None:
                return None

            def update_service(self, zc: Any, type_: str, name: str) -> None:
                self.add_service(zc, type_, name)

        if self._browser is None:
            self._browser = ServiceBrowser(self._zc, SERVICE_TYPE, _Listener())
        return list(self._seen.values())
