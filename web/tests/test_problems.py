# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import re
from pathlib import Path

import pytest
from sqlmodel import Session
from starlette.testclient import TestClient

from app.icons import ICONS
from app.main import app
from app.routes import OPEN_MAX
from app.store.db import get_engine
from app.store.models import Engine, Finding, Level, Outcome, Scan, ScanStatus

PKG = Path(__file__).parents[2] / "styles" / "node_modules" / "bootstrap-icons"


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def scan_with(groups: dict[str, int], pii=False) -> int:
    with Session(get_engine()) as s:
        scan = Scan(
            url="https://example.org/",
            level=Level.AA,
            engines=["axe"],
            status=ScanStatus.DONE,
            privacy_consent=True,
            authorized_by="tester@example.com",
            pii_flags={"US Social Security number": 1} if pii else {},
        )
        s.add(scan)
        s.commit()
        s.refresh(scan)
        for sc, n in groups.items():
            for i in range(n):
                s.add(
                    Finding(
                        scan_id=scan.id,
                        engine=Engine.AXE,
                        outcome=Outcome.FAIL,
                        rule_id=f"rule-{sc}-{i}",
                        sc=sc,
                        wcag_level="A",
                        selector=f"#secret-{sc}-{i}",
                        html_snippet=f"<p>secret {sc} {i}</p>",
                        message=f"secret message {i}",
                        profiles=["desktop"],
                        fingerprint=f"{sc}-{i}",
                    )
                )
        s.commit()
        return scan.id


def findings(html: str) -> list[str]:
    return re.findall(r"<details[^>]*class=\"wa-finding\"[^>]*>.*?</details>", html, re.S)


def test_problems_are_numbered_in_page_order_across_groups(client):
    html = client.get(f"/scans/{scan_with({'2.4.4': 2, '1.1.1': 3})}").text
    nums = [int(n) for n in re.findall(r'<span class="wa-num">Problem (\d+)</span>', html)]
    assert nums == [1, 2, 3, 4, 5]
    assert html.index("Problem 3</span>: axe-core: rule-1.1.1") < html.index("Problem 4</span>")


def test_each_problem_is_a_disclosure_with_decorative_icons(client):
    html = client.get(f"/scans/{scan_with({'1.1.1': 1})}").text
    [item] = findings(html)
    assert "<summary>" in item and "</summary>" in item
    svgs = re.findall(r"<svg[^>]*>", item)
    assert len(svgs) == 3
    for svg in svgs:
        assert 'aria-hidden="true"' in svg and 'focusable="false"' in svg
        assert 'fill="currentColor"' in svg and 'width="1em"' in svg and 'height="1em"' in svg
    assert 'class="wa-icon wa-chev-closed"' in item and 'class="wa-icon wa-chev-open"' in item
    assert "<script" not in html.lower() and "<i " not in html
    assert "style=" not in item  # no inline styles (hash-based CSP)


def test_review_items_use_the_question_icon_and_say_so_in_text(client):
    sid = scan_with({})
    with Session(get_engine()) as s:
        s.add(
            Finding(
                scan_id=sid,
                engine=Engine.ALFA,
                outcome=Outcome.CANT_TELL,
                rule_id="sia-r14",
                sc="2.5.3",
                wcag_level="A",
                profiles=["desktop"],
                fingerprint="r",
            )
        )
        s.commit()
    [item] = findings(client.get(f"/scans/{sid}").text)
    assert ICONS["question-circle"][0][0] in item
    assert ICONS["exclamation-triangle"][0][0] not in item
    assert "Problem 1</span>: Alfa: sia-r14 — needs a person or GitHub Copilot CLI to check" in item


def test_small_groups_start_open_and_large_groups_start_closed(client):
    html = client.get(f"/scans/{scan_with({'1.1.1': OPEN_MAX + 1, '2.4.4': OPEN_MAX})}").text
    items = findings(html)
    closed = [i for i in items if "secret-1.1.1" in i]
    opened = [i for i in items if "secret-2.4.4" in i]
    assert len(closed) == OPEN_MAX + 1 and len(opened) == OPEN_MAX
    assert all(not re.match(r"<details[^>]*\bopen\b", i) for i in closed)
    assert all(re.match(r"<details[^>]*\bopen\b", i) for i in opened)
    assert f"more than {OPEN_MAX} items start with their items closed" in html


def test_masked_findings_stay_masked_inside_the_details(client):
    html = client.get(f"/scans/{scan_with({'1.1.1': 2}, pii=True)}").text
    assert "secret" not in html
    for item in findings(html):
        assert item.count("[hidden until permission is confirmed]") == 3
    assert 'id="provenance"' in html and html.index('id="provenance"') < html.index("wa-finding")


def test_about_page_credits_bootstrap_icons(client):
    assert "Bootstrap Icons (MIT" in client.get("/about").text
    assert "Bootstrap Icons (MIT" in (Path(__file__).parents[2] / "NOTICE").read_text()


@pytest.mark.skipif(not PKG.is_dir(), reason="bootstrap-icons not installed (pnpm install)")
def test_icon_paths_match_the_installed_bootstrap_icons():
    for name, paths in ICONS.items():
        svg = (PKG / "icons" / f"{name}.svg").read_text()
        assert 'viewBox="0 0 16 16"' in svg
        found = re.findall(r'<path(?: fill-rule="(\w+)")? d="([^"]+)"', svg)
        assert [(d, rule or None) for rule, d in found] == paths, name
