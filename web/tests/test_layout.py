# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import html as htmllib
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlmodel import Session
from starlette.testclient import TestClient

from app import ui
from app.main import app
from app.routes import SCANS_PER_PAGE
from app.store.db import get_engine
from app.store.models import Level, Scan, ScanStatus

USER = "tester@example.com"
HOME = ("Home", "/")
RECENT = ("Recent checks", "/scans")


def client() -> TestClient:
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def csrf(c, path="/") -> str:
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).text).group(1)


def add_scans(n: int, verified: bool = False) -> int:
    with Session(get_engine()) as s:
        for _ in range(n):
            scan = Scan(
                url="https://example.org/",
                level=Level.AA,
                engines=["axe"],
                status=ScanStatus.DONE,
                privacy_consent=True,
                authorized_by=USER,
                authorized_at=datetime.now(UTC),
                verified_by=USER if verified else None,
                verification_date=datetime.now(UTC) if verified else None,
            )
            s.add(scan)
        s.commit()
        s.refresh(scan)
        return scan.id


def trail(page: str) -> list[tuple[str, str | None]]:
    nav = re.search(r'<nav aria-label="Breadcrumb">(.*?)</nav>', page, re.S).group(1)
    out = []
    for item in re.findall(r'<li class="breadcrumb-item">(.*?)</li>', nav, re.S):
        link = re.search(r'<a href="([^"]+)">([^<]+)</a>', item)
        if link:
            out.append((htmllib.unescape(link.group(2)), link.group(1)))
        else:
            span = re.search(r'<span aria-current="page">([^<]+)</span>', item)
            out.append((htmllib.unescape(span.group(1)), None))
    return out


def test_breadcrumbs_are_complete_on_every_route():
    # WCAG 2.2 SC 2.4.8 Location: every trail level is a link except the current page
    sid = add_scans(SCANS_PER_PAGE + 1, verified=True)
    c = client()
    expected = {
        "/": [("Home", None)],
        "/scans": [HOME, ("Recent checks", None)],
        "/scans?page=2": [HOME, RECENT, ("Page 2", None)],
        "/scans?page=99": [HOME, RECENT, ("Page not found", None)],
        f"/scans/{sid}": [HOME, RECENT, (f"Check {sid}", None)],
        f"/scans/{sid}/assessment": [
            HOME,
            RECENT,
            (f"Check {sid}", f"/scans/{sid}"),
            ("Checks a person must do", None),
        ],
        f"/scans/{sid}/export": [
            HOME,
            RECENT,
            (f"Check {sid}", f"/scans/{sid}"),
            ("Get the GitHub Copilot CLI request", None),
        ],
        "/settings": [HOME, ("Display settings", None)],
        "/help": [HOME, ("Help", None)],
        "/about": [HOME, ("About and licence", None)],
        "/privacy": [HOME, ("Privacy", None)],
        "/accessibility": [HOME, ("Accessibility statement", None)],
        "/login": [HOME, ("Sign in", None)],
    }
    for path, crumbs in expected.items():
        assert trail(c.get(path).text) == crumbs, path
    shown = c.post(
        f"/scans/{sid}/export",
        data={"csrf": csrf(c), "action": "show", "confirm": "yes"},
    )
    assert trail(shown.text) == [
        HOME,
        RECENT,
        (f"Check {sid}", f"/scans/{sid}"),
        ("GitHub Copilot CLI request", None),
    ]


def _landmarks(page: str) -> list[str]:
    return re.findall(r'<nav aria-label="([^"]+)"', page)


@pytest.mark.parametrize("path", ["/", "/scans", "/help", "/about", "/login"])
def test_header_order_and_unique_landmark_names(path):
    page = client().get(path).text
    assert page.count("<header") == 1 and page.count("<main") == 1
    names = _landmarks(page)
    assert len(names) == len(set(names)), names
    # WCAG 2.2 SC 2.4.3: skip link, brand, nav, account, breadcrumbs, then main content
    order = [
        page.index('class="skip-link"'),
        page.index('<nav aria-label="Main"'),
        page.index('class="nav-link wa-brand"'),
        page.index('<nav aria-label="Account"'),
        page.index('<nav aria-label="Breadcrumb"'),
        page.index("<h1"),
    ]
    assert order == sorted(order)
    assert page.index("<header") < order[1] and page.index("</header>") < order[4]


def test_account_area_when_signed_in():
    page = client().get("/help").text
    account = re.search(r'<nav aria-label="Account".*?</nav>', page, re.S).group(0)
    assert f"Signed in as <strong>{USER}</strong>" in account
    assert "<a " not in account
    assert 'method="post" action="/logout"' in account and 'name="csrf"' in account
    assert ">Sign out</button>" in account and "Sign in" not in account


@pytest.mark.real_auth
def test_account_area_when_signed_out():
    page = client().get("/login").text
    account = re.search(r'<nav aria-label="Account".*?</nav>', page, re.S).group(0)
    assert re.search(r'<a href="/login" aria-current="page" class="nav-link">Sign in</a>', account)
    assert "Sign out" not in account and "Signed in as" not in account


FOOTER_PATHS = ["/", "/scans", "/settings", "/help", "/about", "/privacy", "/accessibility"]
WEB = Path(__file__).parents[1]
SEMVER_TAG = r"v\d+\.\d+\.\d+"


def _footer(page: str) -> str:
    return re.search(r'<footer class="wa-footer">.*?</footer>', page, re.S).group(0)


def test_footer_is_identical_on_every_page_including_sign_in():
    sid = add_scans(1)
    c = client()
    footers = {p: _footer(c.get(p).text) for p in [*FOOTER_PATHS, f"/scans/{sid}"]}
    footers["/login"] = _footer(client().get("/login").text)
    # WCAG 2.2 SC 3.2.3 / 3.2.4: identical on every page
    assert len(set(footers.values())) == 1, sorted(footers)
    footer = footers["/"]
    nav = re.search(r'<nav aria-label="Footer" class="wa-footer-nav">.*?</nav>', footer, re.S)
    assert nav, "footer links sit in nav[aria-label=Footer]"
    for href, text in [
        ("/about", "About and licence"),
        ("/privacy", "Privacy"),
        ("/help", "Help"),
        ("/accessibility", "Accessibility statement"),
        ("https://github.com/rockypod/wa-a11y", "Source code (AGPL-3.0-or-later)"),
    ]:
        assert f'<a href="{href}">{text}</a>' in nav.group(0), text
    assert "Copyright (C) 2026 Kevin Miller (rockypod)" in footer
    assert "modified by" not in footer  # AGPLv3 §7(c) notice only when configured


@pytest.mark.real_auth
def test_source_link_is_on_the_sign_in_page_too():
    # AGPLv3 §13: the Corresponding Source link is offered on every page
    for page in (client().get("/login").text, client().get("/login?next=%2Fscans").text):
        assert f'<a href="{ui.SOURCE_URL}">Source code (AGPL-3.0-or-later)</a>' in _footer(page)


def test_footer_version_matches_the_project_and_release_tag():
    with (WEB / "pyproject.toml").open("rb") as f:
        version = tomllib.load(f)["project"]["version"]
    assert ui.VERSION == f"v{version}" and re.fullmatch(SEMVER_TAG, ui.VERSION)
    assert f"wa-a11y {ui.VERSION}" in _footer(client().get("/").text)
    try:
        tag = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],  # noqa: S607
            cwd=WEB,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        tag = ""
    if re.fullmatch(SEMVER_TAG, tag):
        assert tag == ui.VERSION


def test_footer_shows_modified_by_only_when_configured(monkeypatch):
    monkeypatch.setenv("WA_A11Y_MODIFIED_BY", "Example Organization")
    footer = _footer(client().get("/help").text)
    assert "Based on wa-a11y, modified by Example Organization" in footer


def test_accessibility_statement_page():
    page = client().get("/accessibility").text
    assert "<title>Accessibility statement — WA-A11y</title>" in page
    for text in (
        "level AAA",
        "axe-core and Siteimprove Alfa",
        "what the browser gives to screen readers",
        "manual checklist",
        "Known limits",
        "Report a problem",
    ):
        assert text in page, text
    assert 'href="https://github.com/rockypod/wa-a11y/issues"' in page
