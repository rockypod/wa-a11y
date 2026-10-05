# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

# First line of defence only: the scanner's egress proxy is the real enforcement

import ipaddress
import os
import socket
from urllib.parse import urlsplit, urlunsplit


class UrlRejected(ValueError):
    """Raised with a message that is safe and understandable to show to the user."""


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _allowed_domains() -> list[str]:
    raw = os.environ.get("WA_A11Y_ALLOWED_DOMAINS", "")
    return [d.strip().lower().strip(".") for d in raw.split(",") if d.strip()]


def allow_local_targets() -> bool:
    # Off by default: a scanner that reaches localhost reaches internal services
    return _env_flag("WA_A11Y_ALLOW_LOCAL_TARGETS")


# Link-local, cloud metadata, multicast and reserved ranges are never allowed, even with the opt-in
_LOCAL_OK = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fd00::/8"),
)

_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))

# Must match the scanner's egress guard
_SPECIAL_V6 = (
    ipaddress.ip_network("2001::/23"),
    ipaddress.ip_network("3fff::/20"),
    ipaddress.ip_network("5f00::/16"),
)


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if addr.ipv4_mapped:
        return addr.ipv4_mapped
    if any(addr in net for net in _NAT64):
        return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr.sixtofour


def _unwrap(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.teredo:
            return None  # Teredo tunnels to arbitrary IPv4 — never allowed
        inner = _embedded_ipv4(addr)
        if inner is not None:
            return inner
    return addr


def _is_local_addr(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(addr in net for net in _LOCAL_OK)


def _host_is_local(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        addr = _unwrap(ipaddress.ip_address(host))
    except ValueError:
        return False
    return addr is not None and _is_local_addr(addr)


def is_public_address(ip: str) -> bool:
    try:
        addr = _unwrap(ipaddress.ip_address(ip.split("%", 1)[0]))
    except ValueError:
        return False
    if addr is None:
        return False
    if allow_local_targets() and not addr.is_multicast and _is_local_addr(addr):
        return True
    if isinstance(addr, ipaddress.IPv6Address) and any(addr in n for n in _SPECIAL_V6):
        return False
    return addr.is_global and not addr.is_multicast


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as err:
        raise UrlRejected(f"We could not find the website “{host}”. Check the address.") from err
    return sorted({str(info[4][0]) for info in infos})


def check_scan_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise UrlRejected("Enter the web address of the page to check.")
    if len(url) > 2048:
        raise UrlRejected("That web address is too long.")

    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    allow_http = _env_flag("WA_A11Y_ALLOW_HTTP")
    local_target = allow_local_targets() and _host_is_local(host)
    allow_http_scheme = allow_http or local_target
    allowed_schemes = {"https", "http"} if allow_http_scheme else {"https"}
    if parts.scheme.lower() not in allowed_schemes:
        need = "http:// or https://" if allow_http_scheme else "https://"
        raise UrlRejected(f"The address must start with {need}")
    if parts.username or parts.password:
        raise UrlRejected("The address must not contain a user name or password.")
    if not host:
        raise UrlRejected("The address is missing the website name.")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as err:
        raise UrlRejected("The address has an invalid port number.") from err

    domains = _allowed_domains()
    if domains and not any(host == d or host.endswith("." + d) for d in domains):
        raise UrlRejected("This checker only scans approved websites.")

    addresses = _resolve(host, port)
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise UrlRejected(
            "This address points to an internal or private network. "
            "Only public websites can be checked."
        )

    netloc = host if parts.port is None else f"{host}:{parts.port}"
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]" if parts.port is None else f"[{host}]:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))
