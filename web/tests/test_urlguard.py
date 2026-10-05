# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import socket

import pytest

from app.urlguard import UrlRejected, check_scan_url, is_public_address

PUBLIC = "93.184.215.14"


@pytest.fixture
def dns(monkeypatch):
    table: dict[str, list[str]] = {}

    def fake(host, port, *a, **kw):
        if host not in table:
            raise socket.gaierror("not found")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    monkeypatch.delenv("WA_A11Y_ALLOW_HTTP", raising=False)
    monkeypatch.delenv("WA_A11Y_ALLOWED_DOMAINS", raising=False)
    monkeypatch.delenv("WA_A11Y_ALLOW_LOCAL_TARGETS", raising=False)
    return table


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.8.129",
        "169.254.169.254",
        "100.93.208.5",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fd7a:115c:a1e0::1",
        "::ffff:10.0.0.1",
        "224.0.0.1",
        "nonsense",
        # internal IPv4 in hex-mapped, NAT64, 6to4 and Teredo forms
        "::ffff:7f00:1",
        "0:0:0:0:0:ffff:c0a8:801",
        "64:ff9b::a00:1",
        "64:ff9b::7f00:1",
        "64:ff9b:1::a9fe:a9fe",
        "2002:a00:1::1",
        "2001:0:4136:e378:8000:63bf:3fff:fdd2",
    ],
)
def test_non_public_addresses(ip):
    assert not is_public_address(ip)


@pytest.mark.parametrize(
    "ip", ["1.1.1.1", "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808"]
)
def test_public_addresses(ip):
    assert is_public_address(ip)


def test_accepts_public_https_and_normalises(dns):
    dns["www.sub.example.net"] = [PUBLIC]
    assert (
        check_scan_url("  HTTPS://WWW.SUB.EXAMPLE.NET/a?b=1#frag ")
        == "https://www.sub.example.net/a?b=1"
    )
    assert check_scan_url("https://www.sub.example.net") == "https://www.sub.example.net/"


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("", "Enter the web address"),
        ("ftp://example.org/", "must start with https://"),
        ("http://example.org/", "must start with https://"),
        ("javascript:alert(1)", "must start with https://"),
        ("https://user:pw@example.org/", "user name or password"),
        ("https:///path", "missing the website name"),
        ("https://example.org:99999/", "invalid port"),
        ("https://unknown.invalid/", "could not find"),
    ],
)
def test_rejects_bad_input(dns, url, message):
    dns["example.org"] = [PUBLIC]
    with pytest.raises(UrlRejected, match=message):
        check_scan_url(url)


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["10.1.2.3"], ["169.254.169.254"], ["100.93.208.5"], [PUBLIC, "192.168.1.1"]],
)
def test_rejects_hosts_resolving_to_internal(dns, addresses):
    dns["sneaky.example"] = addresses  # any internal address (even mixed with public) is refused
    with pytest.raises(UrlRejected, match="internal or private network"):
        check_scan_url("https://sneaky.example/")


def test_rejects_ip_literals_that_are_internal(dns):
    dns["127.0.0.1"] = ["127.0.0.1"]
    with pytest.raises(UrlRejected, match="internal"):
        check_scan_url("https://127.0.0.1/")


def test_http_allowed_only_when_configured(dns, monkeypatch):
    dns["example.org"] = [PUBLIC]
    monkeypatch.setenv("WA_A11Y_ALLOW_HTTP", "1")
    assert check_scan_url("http://example.org/") == "http://example.org/"


def test_domain_allowlist(dns, monkeypatch):
    dns["www.sub.example.net"] = [PUBLIC]
    dns["sub.example.net.evil.com"] = [PUBLIC]
    dns["example.org"] = [PUBLIC]
    monkeypatch.setenv("WA_A11Y_ALLOWED_DOMAINS", "sub.example.net, example.net")
    assert check_scan_url("https://www.sub.example.net/")
    for bad in ("https://example.org/", "https://sub.example.net.evil.com/"):
        with pytest.raises(UrlRejected, match="approved websites"):
            check_scan_url(bad)


def test_local_targets_need_the_opt_in(dns):
    dns["localhost"] = ["127.0.0.1"]
    dns["127.0.0.1"] = ["127.0.0.1"]
    dns["10.0.0.5"] = ["10.0.0.5"]
    dns["::1"] = ["::1"]
    for url in (
        "https://localhost:3000/",
        "https://127.0.0.1:8080/",
        "https://10.0.0.5/",
        "https://[::1]:5173/",
        "http://localhost:3000/",  # http:// needs the opt-in too, not just WA_A11Y_ALLOW_HTTP
    ):
        with pytest.raises(UrlRejected):
            check_scan_url(url)


def test_local_targets_allowed_when_opted_in(dns, monkeypatch):
    monkeypatch.setenv("WA_A11Y_ALLOW_LOCAL_TARGETS", "1")
    dns["localhost"] = ["127.0.0.1"]
    dns["127.0.0.1"] = ["127.0.0.1"]
    dns["192.168.1.20"] = ["192.168.1.20"]
    dns["::1"] = ["::1"]
    assert check_scan_url("http://localhost:3000") == "http://localhost:3000/"
    assert check_scan_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080/"
    assert check_scan_url("http://192.168.1.20") == "http://192.168.1.20/"
    assert check_scan_url("http://[::1]:5173") == "http://[::1]:5173/"
    assert check_scan_url("https://localhost:3000") == "https://localhost:3000/"


def test_local_opt_in_still_blocks_link_local_metadata_and_cgnat(dns, monkeypatch):
    monkeypatch.setenv("WA_A11Y_ALLOW_LOCAL_TARGETS", "1")
    dns["169.254.169.254"] = ["169.254.169.254"]
    dns["fe80::1"] = ["fe80::1"]
    dns["100.93.208.5"] = ["100.93.208.5"]  # CGNAT/Tailscale is not a private range
    for url in ("https://169.254.169.254/", "https://[fe80::1]/", "https://100.93.208.5/"):
        with pytest.raises(UrlRejected, match="internal or private network"):
            check_scan_url(url)
    with pytest.raises(UrlRejected):  # metadata IP over http: not a local target either way
        check_scan_url("http://169.254.169.254/")
    assert not is_public_address("169.254.169.254")
    assert not is_public_address("fe80::1")


def test_local_opt_in_does_not_open_http_for_public_sites(dns, monkeypatch):
    monkeypatch.setenv("WA_A11Y_ALLOW_LOCAL_TARGETS", "1")
    dns["example.org"] = [PUBLIC]
    with pytest.raises(UrlRejected, match="must start with https://"):
        check_scan_url("http://example.org/")


@pytest.mark.parametrize("ip", ["2001:2::1", "2001:10::1", "2001:20::1", "3fff::1", "5f00::1"])
def test_special_use_ipv6_matches_scanner_guard(ip):
    assert not is_public_address(ip)  # same answer as scanner/src/egress.ts
