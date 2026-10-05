# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlmodel import Session, select
from starlette.testclient import TestClient

from app import jobs
from app.main import app
from app.prompts import build_prompt
from app.store.db import get_engine, make_engine
from app.store.models import Engine, Finding, Level, Outcome, Scan, ScanStatus

WEB = Path(__file__).parents[1]


def _aria(rule_id, outcome, sc=("1.3.1",), level="A", selector="", html="", message="ok"):
    return {
        "source": "automated",
        "engine": "aria-tree",
        "outcome": outcome,
        "ruleId": rule_id,
        "sc": list(sc),
        "wcagLevel": level,
        "selector": selector,
        "html": html,
        "message": message,
        "impact": None,
        "helpUrl": "https://www.w3.org/WAI/WCAG22/Understanding/page-titled.html",
        "profiles": ["desktop"],
    }


RESULT = {
    "findings": [
        _aria("aria-page-title", "fail", ("2.4.2",), selector="page › title", message="No title."),
        _aria("aria-main-landmark", "pass", ("1.3.1", "2.4.1"), message="One main landmark."),
        _aria("aria-heading-order", "cantTell", selector='page › heading 2 "B"', html="- heading"),
        _aria(
            "aria-control-names",
            "fail",
            ("1.3.1", "4.1.2"),
            selector="page › main › textbox 1",
            html="- textbox",
            message="This textbox has no accessible name. Give it a visible <label for>.",
        ),
        {**_aria("axe-rule", "fail", ("1.1.1",)), "engine": "axe", "ruleId": "image-alt"},
    ]
}


def _scan(**kw) -> Scan:
    with Session(get_engine()) as s:
        scan = Scan(
            url="https://example.org/",
            level=Level.AA,
            engines=["axe"],
            profiles=["desktop"],
            status=ScanStatus.DONE,
            privacy_consent=True,
            authorized_by="tester@example.com",
            **kw,
        )
        s.add(scan)
        s.commit()
        s.refresh(scan)
        return scan


def _store(scan: Scan, result: dict) -> list[Finding]:
    findings = jobs._to_findings(scan, result)
    with Session(get_engine()) as s:
        for f in findings:
            s.add(f)
        s.commit()
        for f in findings:
            s.refresh(f)
    return findings


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_ingest_keeps_aria_passes_and_the_not_run_item_as_an_error():
    scan = _scan()
    result = {
        "findings": [
            *RESULT["findings"],
            _aria("aria-tree-not-run", "cantTell", (), None, message="could not run"),
            {**_aria("x", "pass"), "engine": "axe"},
        ]
    }
    by_rule = {f.rule_id: f for f in jobs._to_findings(scan, result)}
    assert by_rule["aria-main-landmark"].outcome is Outcome.PASS
    assert by_rule["aria-main-landmark"].engine is Engine.ARIA_TREE
    assert by_rule["aria-page-title"].outcome is Outcome.FAIL
    assert by_rule["aria-heading-order"].outcome is Outcome.CANT_TELL
    assert by_rule["aria-tree-not-run"].outcome is Outcome.ERROR
    assert "x" not in by_rule
    assert by_rule["aria-control-names"].sc == "1.3.1,4.1.2"
    assert not by_rule["aria-control-names"].advisory


def test_results_page_shows_a_separate_exposed_to_at_card(client):
    scan = _scan()
    _store(scan, RESULT)
    html = client.get(f"/scans/{scan.id}").text
    card = html[html.index('id="screen-reader"') : html.index('id="copilot"')]
    assert "Screen-reader structure (exposed to assistive technology)" in card
    assert "not a screen-reader test" in card
    assert "Problem: </strong>Page title" in card and "Passed: </strong>One main landmark" in card
    assert "Check by hand: </strong>Heading levels in order" in card
    assert "&lt;label for&gt;" in card and "<label for>" not in card  # page-derived text is escaped
    assert "Still check with a screen reader" in card
    assert "Check names and roles with a screen reader" in card
    details = html[html.index('id="details"') : html.index('id="screen-reader"')]
    assert "aria-page-title" not in details and "image-alt" in details
    summary = html[html.index('id="summary"') : html.index("</table>")]
    badge = r"<span class=\"wa-count badge rounded-pill\">1</span>"
    assert re.search(r"Problems found</th>\s*<td>\s*" + badge, summary)
    assert "2 problems, 1 to check by hand, 1 passed" in summary
    assert "<script" not in html.lower()


def test_scans_without_observations_say_not_run_never_pass(client):
    scan = _scan()
    html = client.get(f"/scans/{scan.id}").text
    card = html[html.index('id="screen-reader"') : html.index('id="copilot"')]
    assert "Not run." in card and "nothing here is a pass" in card
    assert "Passed" not in card


def test_not_run_item_is_shown_as_not_run(client):
    scan = _scan()
    _store(
        scan,
        {"findings": [_aria("aria-tree-not-run", "cantTell", (), None, message="Tree missing.")]},
    )
    html = client.get(f"/scans/{scan.id}").text
    assert "Not run. </strong>Tree missing." in html
    assert re.search(r"Screen-reader structure</th>\s*<td>\s*<a [^>]*>Not run</a>", html)


def test_private_data_masks_observations_until_permission(client):
    scan = _scan(pii_flags={"email address": 1})
    _store(
        scan,
        {
            "findings": [
                _aria(
                    "aria-link-names",
                    "fail",
                    ("2.4.4",),
                    selector='page › link 1 "jane@example.org"',
                    message="No name.",
                )
            ]
        },
    )
    html = client.get(f"/scans/{scan.id}").text
    assert "jane@example.org" not in html
    assert "[hidden until permission is confirmed]" in html


def test_prompt_lists_failed_observations_only():
    scan = _scan(verified_by="tester@example.com", verification_date=datetime.now(UTC))
    findings = _store(scan, RESULT)
    prompt = build_prompt(scan, findings)
    assert "aria-control-names" in prompt and "aria-page-title" in prompt
    assert "Screen-reader structure (exposed to assistive technology)" in prompt
    assert "Accessibility tree entry" in prompt
    assert "aria-main-landmark" not in prompt
    assert "aria-heading-order" not in prompt


def _cfg(url: str) -> Config:
    cfg = Config(str(WEB / "alembic.ini"))
    cfg.set_main_option("script_location", str(WEB / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migration_adds_the_engine_and_downgrade_removes_only_its_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(_cfg(url), "head")
    engine = make_engine(url)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO scan (id, url, level, engines, profiles, status, tool_versions, "
                "blocked_requests, privacy_consent, automated_precheck, pii_flags, created_at) "
                "VALUES (1, 'https://example.org/', 'AA', '[]', '[]', 'DONE', '{}', '[]', 1, 1, "
                "'{}', '2026-10-04 00:00:00')"
            )
        )
        for i, eng in enumerate(("AXE", "ARIA_TREE")):
            c.execute(
                text(
                    "INSERT INTO finding (scan_id, source, engine, outcome, advisory, rule_id, "
                    "selector, html_snippet, message, profiles, fingerprint) VALUES "
                    "(1, 'AUTOMATED', :eng, 'PASS', 0, :rule, '', '', '', '[]', :fp)"
                ),
                {"eng": eng, "rule": f"r{i}", "fp": f"f{i}"},
            )
    with Session(engine) as s:
        assert {f.engine for f in s.exec(select(Finding))} == {Engine.AXE, Engine.ARIA_TREE}
    engine.dispose()
    command.downgrade(_cfg(url), "8fd66209ca51")
    engine = make_engine(url)
    with engine.connect() as c:
        assert c.execute(text("SELECT engine FROM finding")).scalars().all() == ["AXE"]
    engine.dispose()
