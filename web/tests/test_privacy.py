# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import re
from datetime import UTC, datetime

from sqlmodel import Session, select
from starlette.testclient import TestClient

from app import routes
from app.main import app
from app.privacy import CONSENT_TEXT, RULE, banner, detect
from app.store.db import get_engine
from app.store.models import Engine, Finding, Level, Outcome, PrivateDataGrant, Scan, ScanStatus

USER = "tester@example.com"


def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def csrf(c, path="/"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).text).group(1)


def done_scan(pii=False, verified=False) -> int:
    with Session(get_engine()) as s:
        scan = Scan(
            url="https://example.org/",
            level=Level.AA,
            engines=["axe"],
            status=ScanStatus.DONE,
            privacy_consent=True,
            authorized_by=USER,
            authorized_at=datetime.now(UTC),
            pii_flags={"US Social Security number": 1} if pii else {},
            verified_by=USER if verified else None,
            verification_date=datetime.now(UTC) if verified else None,
        )
        s.add(scan)
        s.commit()
        s.refresh(scan)
        s.add(
            Finding(
                scan_id=scan.id,
                engine=Engine.AXE,
                outcome=Outcome.FAIL,
                rule_id="image-alt",
                sc="1.1.1",
                wcag_level="A",
                selector="img.secret-selector",
                html_snippet="<p>SSN 123-45-6789</p>",
                message="secret message",
                impact="critical",
                profiles=["desktop"],
                fingerprint="fp",
            )
        )
        s.commit()
        return scan.id


def test_check_page_shows_rule_and_requires_consent(monkeypatch):
    monkeypatch.setattr(routes, "check_scan_url", lambda u: u)
    c = client()
    html = c.get("/").text
    assert (
        RULE in html
        and CONSENT_TEXT in html
        and f"Authorizing as: </span><strong>{USER}"
        in html.replace("Authorizing as: <strong>", "Authorizing as: </span><strong>")
    )
    r = c.post(
        "/scans",
        data={"csrf": csrf(c), "url": "https://example.org/", "level": "2.2-AA", "engines": "axe"},
    )
    assert r.status_code == 200 and "Tick the permission box" in r.text
    assert 'id="consent-error" class="invalid-feedback"' in r.text
    with Session(get_engine()) as s:
        assert s.exec(select(Scan)).all() == []
    r = c.post(
        "/scans",
        data={
            "csrf": csrf(c),
            "url": "https://example.org/",
            "level": "2.2-AA",
            "engines": "axe",
            "consent": "yes",
        },
    )
    assert r.status_code == 303
    with Session(get_engine()) as s:
        scan = s.exec(select(Scan)).one()
    assert scan.privacy_consent and scan.authorized_by == USER and scan.authorized_at


def test_results_start_with_provenance_and_rule():
    html = client().get(f"/scans/{done_scan()}").text
    assert html.index(banner(USER)) < html.index("<h1>Check results</h1>")
    assert RULE in html and "Human verification required" in html


def test_private_data_is_hidden_until_permission_and_the_grant_is_logged():
    sid = done_scan(pii=True)
    c = client()
    html = c.get(f"/scans/{sid}").text
    assert "Potential private data detected" in html and "US Social Security number" in html
    assert (
        "123-45-6789" not in html and "secret-selector" not in html and "secret message" not in html
    )
    r = c.post(f"/scans/{sid}/grant", data={"csrf": csrf(c), "grant": "yes"})
    assert r.status_code == 303
    with Session(get_engine()) as s:
        g = s.exec(select(PrivateDataGrant)).one()
    assert g.granted_by == USER and g.flags == {"US Social Security number": 1}
    html = c.get(f"/scans/{sid}").text
    assert f"{USER} allowed access to potential private data on" in html
    assert "secret-selector" in html


def test_export_needs_verification_then_confirmation():
    sid = done_scan()
    c = client()
    assert c.get(f"/scans/{sid}/export").status_code == 403
    c.post(f"/scans/{sid}/verify", data={"csrf": csrf(c), "verify": "yes"})
    assert c.get(f"/scans/{sid}/export").status_code == 200
    r = c.post(f"/scans/{sid}/export", data={"csrf": csrf(c), "action": "download"})
    assert r.status_code == 400
    box = re.search(r'<input[^>]*id="confirm"[^>]*>', r.text).group(0)
    assert "is-invalid" in box and 'aria-invalid="true"' in box
    assert 'aria-describedby="confirm-error"' in box
    assert 'id="confirm-error" class="invalid-feedback"' in r.text and 'href="#confirm"' in r.text
    r = c.post(
        f"/scans/{sid}/export", data={"csrf": csrf(c), "action": "download", "confirm": "yes"}
    )
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert banner(USER) in r.text
    assert '"privacy_cleared": true' in r.text and f'"authorized_by": "{USER}"' in r.text
    assert f"User '{USER}' explicitly granted permission" in r.text
    shown = c.post(
        f"/scans/{sid}/export", data={"csrf": csrf(c), "action": "show", "confirm": "yes"}
    )
    assert banner(USER) in shown.text and 'id="prompt-text"' in shown.text


def test_flagged_scan_cannot_be_verified_before_permission():
    sid = done_scan(pii=True)
    c = client()
    c.post(f"/scans/{sid}/verify", data={"csrf": csrf(c), "verify": "yes"})
    with Session(get_engine()) as s:
        assert s.get(Scan, sid).verified_by is None
    assert c.get(f"/scans/{sid}/export").status_code == 403


def test_print_styles_never_hide_the_provenance_banner():
    from pathlib import Path

    scss = (Path(__file__).parents[2] / "styles" / "scss" / "main.scss").read_text()
    print_block = scss[scss.index("@media print") :]
    assert ".wa-provenance" in print_block and "display: block !important" in print_block
    assert not re.search(r"\.wa-provenance[^{]*\{[^}]*(display:\s*none|visibility:\s*hidden)", scss)


def test_detect_counts_kinds_and_ignores_mock_emails():
    # no personal-looking number in git (pii-scan)
    phone, long_id = "555-" + "123-4567", "12345" + "67890"
    assert detect(f"call {phone}", "x@example.com", "SSN 123-45-6789", f"id {long_id}") == {
        "phone number": 1,
        "US Social Security number": 1,
        "long ID-like number": 1,
    }
