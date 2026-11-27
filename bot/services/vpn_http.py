"""
Общий сетевой помощник для публикаторов (Instagram, TikTok):
маршрутизирует исходящие HTTP-запросы через AWG VPN (SHORTS_YOUTUBE_SOURCE)
и резолвит внешние API-домены через UDP DNS / DoH внутри туннеля.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import struct

import aiohttp
from aiohttp.abc import AbstractResolver

logger = logging.getLogger(__name__)

DEFAULT_VPN_SUFFIXES = (
    ".facebook.com",
    ".instagram.com",
    ".tiktokapis.com",
)


class VpnDnsResolver(AbstractResolver):
    """Резолвит зарубежные API-домены через UDP DNS и 8.8.4.4 DoH по AWG VPN."""

    def __init__(self, vpn_source: str, suffixes: tuple[str, ...] = DEFAULT_VPN_SUFFIXES):
        self.vpn_source = vpn_source
        self.suffixes = suffixes
        self.default = aiohttp.ThreadedResolver()
        self._cache: dict[str, list[str]] = {}

    def _matches(self, host: str) -> bool:
        h = host.lower().rstrip(".")
        return any(h == s.lstrip(".") or h.endswith(s) for s in self.suffixes)

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if self._matches(host):
            ips = self._cache.get(host)
            if not ips:
                ips = await self._resolve_via_vpn(host)
                if ips:
                    self._cache[host] = ips
            if ips:
                return [
                    {
                        "hostname": host,
                        "host": ip,
                        "port": port,
                        "family": socket.AF_INET,
                        "proto": 0,
                        "flags": socket.AI_NUMERICHOST,
                    }
                    for ip in ips
                ]
        return await self.default.resolve(host, port, family)

    def _udp_dns_a_sync(self, server: str, host: str) -> list[str]:
        qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in host.split(".")) + b"\x00"
        pkt = struct.pack(">HHHHHH", 0x1A2B, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", 1, 1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(2.5)
            sock.bind((self.vpn_source, 0))
            sock.sendto(pkt, (server, 53))
            data, _ = sock.recvfrom(1024)
        finally:
            sock.close()

        idx = 12 + len(qname) + 4
        ancount = struct.unpack(">H", data[6:8])[0]
        ips: list[str] = []
        for _ in range(ancount):
            if idx >= len(data):
                break
            if (data[idx] & 0xC0) == 0xC0:
                idx += 2
            else:
                while idx < len(data) and data[idx] != 0:
                    idx += 1 + data[idx]
                idx += 1
            if idx + 10 > len(data):
                break
            rtype, _, _, rdlen = struct.unpack(">HHIH", data[idx:idx + 10])
            idx += 10
            if rtype == 1 and rdlen == 4 and idx + 4 <= len(data):
                ips.append(socket.inet_ntoa(data[idx:idx + 4]))
            idx += rdlen
        return ips

    async def _resolve_via_vpn(self, host: str) -> list[str]:
        for dns_ip in ("8.8.4.4", "9.9.9.9", "10.2.0.1"):
            try:
                ips = await asyncio.to_thread(self._udp_dns_a_sync, dns_ip, host)
                if ips:
                    return ips
            except Exception:
                continue
        try:
            conn = aiohttp.TCPConnector(local_addr=(self.vpn_source, 0), family=socket.AF_INET)
            async with aiohttp.ClientSession(connector=conn) as sess:
                async with sess.get(
                    "https://8.8.4.4/resolve",
                    params={"name": host, "type": "A"},
                    timeout=aiohttp.ClientTimeout(total=6),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        return [
                            str(a["data"])
                            for a in data.get("Answer", [])
                            if a.get("type") == 1 and a.get("data")
                        ]
        except Exception as e:
            logger.debug("VPN DNS lookup for %s failed: %s", host, e)
        return []

    async def close(self) -> None:
        await self.default.close()


def build_vpn_connector(env_flag: str, default_use_vpn: bool = True) -> aiohttp.TCPConnector:
    """Создаёт aiohttp.TCPConnector с привязкой к AWG VPN и VPN-DNS при наличии туннеля."""
    default_str = "true" if default_use_vpn else "false"
    use_vpn = os.getenv(env_flag, default_str).lower() in ("true", "1", "yes")
    vpn_source = os.getenv("SHORTS_YOUTUBE_SOURCE", "").strip()
    if use_vpn and vpn_source:
        return aiohttp.TCPConnector(
            local_addr=(vpn_source, 0),
            family=socket.AF_INET,
            resolver=VpnDnsResolver(vpn_source),
        )
    return aiohttp.TCPConnector()
