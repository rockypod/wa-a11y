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

from app.assessment import results
from app.main import app
from app.prompts import build_prompt
from app.store.db import get_engine
from app.store.models import (
    AssessmentResult,
    Level,
    PrivateDataGrant,
    ReviewStatus,
    Scan,
    ScanStatus,
)

USER = "tester@example.com"
MAIL = "jane.doe" + "@" + "dept.invalid"  # no personal-looking address in git (pii-scan)


def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def csrf(c, path="/"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).text).group(1)


def done_scan(level=Level.AA, status=ScanStatus.DONE, **kw) -> int:
    with Session(get_engine()) as s:
        scan = Scan(
            url="https://example.org/",
            level=level,
            engines=["axe"],
            status=status,
            privacy_consent=True,
            authorized_by=USER,
            authorized_at=datetime.now(UTC),
            **kw,
        )
        s.add(scan)
        s.commit()
        s.refresh(scan)
        return scan.id


def _tag(html: str, element_id: str) -> str:
    return re.search(rf'<input[^>]*id="{element_id}"[^>]*>', html).group(0)


def stored(sid) -> dict[str, AssessmentResult]:
    with Session(get_engine()) as s:
        return results.saved(s, sid)


def test_items_follow_the_scan_level():
    aa = {i["level"] for i in results.applicable(Level.AA)}
    assert aa == {"A", "AA"}
    assert len(results.applicable(Level.AAA)) == len(results.checklist()["items"])


def test_page_lists_applicable_items_with_labelled_controls():
    sid = done_scan()
    html = client().get(f"/scans/{sid}/assessment").text
    assert "<script" not in html.lower()
    total = len(results.applicable(Level.AA))
    assert f"0 of {total} checks recorded" in html
    assert "version 1" in html and f"Recording as: </strong>{USER}" in html
    assert '<h2 id="principle-2">Operable</h2>' in html
    assert "Use the whole page with just a keyboard" in html
    assert 'id="item-reading-level"' not in html  # WCAG 2.2: a Level AAA item is not on a AA check
    for value, label in (
        ("pass", "Pass"),
        ("fail", "Fail"),
        ("needs-review", "Needs review"),
        ("not-applicable", "Not applicable"),
    ):
        rid = f"status-kbd-basics-{value}"
        assert (
            f'id="{rid}"' in html and f'<label for="{rid}" class="form-check-label">{label}' in html
        )
    assert "<legend>Result: Use the whole page with just a keyboard</legend>" in html
    area = re.search(r'<textarea[^>]*id="notes-kbd-basics"[^>]*>', html).group(0)
    assert 'maxlength="2000"' in area and 'aria-describedby="notes-kbd-basics-hint"' in area
    assert 'id="notes-kbd-basics-hint"' in html and "Up to 2000 characters" in html
    aaa = client().get(f"/scans/{done_scan(level=Level.AAA)}/assessment").text
    assert 'id="item-reading-level"' in aaa


def test_save_records_reviewer_and_only_changed_items():
    sid = done_scan()
    c = client()
    data = {
        "csrf": csrf(c),
        "status-kbd-basics": "fail",
        "notes-kbd-basics": "The menu button did nothing on Enter.",
        "status-kbd-trap": "pass",
        "notes-kbd-trap": "",
    }
    r = c.post(f"/scans/{sid}/assessment", data=data)
    assert r.status_code == 303 and r.headers["location"].endswith("/assessment?saved=1")
    rows = stored(sid)
    assert set(rows) == {"kbd-basics", "kbd-trap"}
    assert rows["kbd-basics"].status is ReviewStatus.FAIL and rows["kbd-basics"].reviewer == USER
    assert rows["kbd-basics"].notes == "The menu button did nothing on Enter."
    first_time = rows["kbd-trap"].reviewed_at
    html = c.get(f"/scans/{sid}/assessment?saved=1").text
    assert 'role="status"' in html and "2 of" in html
    assert " checked " in _tag(html, "status-kbd-basics-fail")
    assert "Recorded as Fail by tester@example.com on" in html
    data.update({"csrf": csrf(c), "status-kbd-basics": "needs-review"})
    c.post(f"/scans/{sid}/assessment", data=data)
    rows = stored(sid)
    assert rows["kbd-basics"].status is ReviewStatus.NEEDS_REVIEW
    assert rows["kbd-trap"].reviewed_at == first_time


def test_errors_keep_entries_and_link_to_fields():
    sid = done_scan()
    c = client()
    r = c.post(
        f"/scans/{sid}/assessment",
        data={
            "csrf": csrf(c),
            "notes-kbd-basics": "Saw a trap",
            "status-kbd-trap": "fail",
            "notes-kbd-trap": "x" * 2001,
        },
    )
    assert r.status_code == 400
    html = r.text
    assert html.index('id="error-summary"') < html.index('id="about-checks"')
    assert 'href="#status-kbd-basics-pass"' in html and 'href="#notes-kbd-trap"' in html
    radio = re.search(r'<input[^>]*id="status-kbd-basics-pass"[^>]*>', html).group(0)
    assert "is-invalid" in radio and 'aria-invalid="true"' in radio
    assert 'aria-describedby="status-kbd-basics-error"' in radio
    area = re.search(r'<textarea[^>]*id="notes-kbd-trap"[^>]*>', html).group(0)
    assert (
        "is-invalid" in area
        and 'aria-describedby="notes-kbd-trap-hint notes-kbd-trap-error"' in area
    )
    assert 'id="notes-kbd-trap-error" class="invalid-feedback"' in html
    assert ">Saw a trap</textarea>" in html
    assert " checked " in _tag(html, "status-kbd-trap-fail")
    assert stored(sid) == {}


def test_expired_form_keeps_entries():
    sid = done_scan()
    r = client().post(
        f"/scans/{sid}/assessment",
        data={"csrf": "stale", "status-kbd-basics": "pass", "notes-kbd-basics": "ok"},
    )
    assert r.status_code == 403 and 'href="#save"' in r.text and ">ok</textarea>" in r.text
    assert stored(sid) == {}


def test_unfinished_or_missing_scans_have_no_checklist():
    c = client()
    assert c.get("/scans/999/assessment").status_code == 404
    sid = done_scan(status=ScanStatus.RUNNING)
    assert c.get(f"/scans/{sid}/assessment").status_code == 303


def test_results_page_shows_progress_separately_from_machine_output():
    sid = done_scan()
    with Session(get_engine()) as s:
        scan = s.get(Scan, sid)
        results.record(s, scan, "kbd-basics", ReviewStatus.FAIL, USER, "")
    html = client().get(f"/scans/{sid}").text
    total = len(results.applicable(Level.AA))
    manual = html[html.index('id="manual"') :]
    assert f"1 of {total} checks recorded" in manual and "1 fail, 0 need review" in manual
    assert f'href="/scans/{sid}/assessment"' in manual
    assert "automated tools' results only" in html[: html.index('id="manual"')]
    verify = html[html.index('id="verify-heading"') : html.index('id="summary"')]
    assert f"1 of {total} checks recorded" in verify and "not required to verify" in verify


def test_verification_does_not_require_the_checklist():
    sid = done_scan()
    c = client()
    c.post(f"/scans/{sid}/verify", data={"csrf": csrf(c), "verify": "yes"})
    with Session(get_engine()) as s:
        assert s.get(Scan, sid).verified_by == USER


def test_notes_on_unreleased_scan_save_but_stay_hidden():
    sid = done_scan(pii_flags={"US Social Security number": 1})
    c = client()
    html = c.get(f"/scans/{sid}/assessment").text
    assert "Potential private data detected" in html
    r = c.post(
        f"/scans/{sid}/assessment",
        data={"csrf": csrf(c), "status-kbd-basics": "fail", "notes-kbd-basics": f"saw {MAIL}"},
    )
    assert r.status_code == 303
    assert stored(sid)["kbd-basics"].notes == f"saw {MAIL}"
    html = c.get(f"/scans/{sid}/assessment").text
    assert MAIL not in html and 'id="notes-kbd-basics"' not in html
    assert "hidden until permission" in html
    c.post(f"/scans/{sid}/assessment", data={"csrf": csrf(c), "status-kbd-basics": "pass"})
    row = stored(sid)["kbd-basics"]
    assert row.status is ReviewStatus.PASS and row.notes == f"saw {MAIL}"


def test_new_private_data_in_notes_after_a_grant_needs_a_new_grant():
    flags = {"US Social Security number": 1}
    sid = done_scan(pii_flags=flags, verified_by=USER, verification_date=datetime.now(UTC))
    with Session(get_engine()) as s:
        s.add(PrivateDataGrant(scan_id=sid, granted_by=USER, flags=flags))
        s.commit()
    c = client()
    assert c.get(f"/scans/{sid}/export").status_code == 200
    c.post(
        f"/scans/{sid}/assessment",
        data={"csrf": csrf(c), "status-kbd-basics": "fail", "notes-kbd-basics": "clean"},
    )
    assert c.get(f"/scans/{sid}/export").status_code == 200
    c.post(
        f"/scans/{sid}/assessment",
        data={"csrf": csrf(c), "status-kbd-basics": "fail", "notes-kbd-basics": f"see {MAIL}"},
    )
    with Session(get_engine()) as s:
        assert s.get(Scan, sid).pii_flags == {"email address": 1}
    assert c.get(f"/scans/{sid}/export").status_code == 403
    html = c.get(f"/scans/{sid}").text
    assert "Potential private data detected" in html and 'action="/scans/' in html
    assert "New since the last permission: email address" in html
    assert f'/scans/{sid}/grant"' in html
    c.post(f"/scans/{sid}/grant", data={"csrf": csrf(c), "grant": "yes"})
    with Session(get_engine()) as s:
        assert len(s.exec(select(PrivateDataGrant)).all()) == 2
    assert c.get(f"/scans/{sid}/export").status_code == 200
    assert "Potential private data detected" not in c.get(f"/scans/{sid}").text


def test_export_lists_failed_checks_but_never_notes():
    sid = done_scan(verified_by=USER, verification_date=datetime.now(UTC))
    with Session(get_engine()) as s:
        scan = s.get(Scan, sid)
        results.record(s, scan, "kbd-basics", ReviewStatus.FAIL, USER, "secret reviewer note")
        results.record(s, scan, "kbd-trap", ReviewStatus.PASS, USER, "")
        results.record(s, scan, "focus-order", ReviewStatus.NEEDS_REVIEW, USER, "")
        rows = list(results.saved(s, sid).values())
        text = build_prompt(scan, [], [], rows)
    assert "## Manual check results" in text
    assert "- Fail: Use the whole page with just a keyboard — WCAG: 2.1.1 Keyboard" in text
    assert "- Needs review: Check the focus order makes sense" in text
    assert "Check you can always leave with the keyboard" not in text
    assert "secret reviewer note" not in text
    c = client()
    r = c.post(
        f"/scans/{sid}/export", data={"csrf": csrf(c), "action": "download", "confirm": "yes"}
    )
    assert "## Manual check results" in r.text and "secret reviewer note" not in r.text
