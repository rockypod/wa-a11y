# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

from datetime import UTC, datetime

from sqlmodel import Session

from app.accounts import create_user
from app.store.db import get_engine
from app.assessment.results import CHECKLIST_ID, checklist
from app.store.models import (
    AssessmentResult, Engine, Finding, Level, Outcome, PrivateDataGrant, ReviewStatus, Scan,
    ScanStatus)

USER = "selfscan@example.com"
NOW = datetime(2026, 10, 3, 9, 30, tzinfo=UTC)
AUTH = {"privacy_consent": True, "authorized_by": USER, "authorized_at": NOW}
LONG = "https://www.example.org/a-very-long-path/that-should-wrap-on-small-screens?with=query&and=more"

# Self-scan pages reference scans by id: append new rows, never renumber.
with Session(get_engine()) as s:
    queued = Scan(**AUTH, url="https://www.example.net/", level=Level.AA, engines=["axe", "alfa"],
                  status=ScanStatus.QUEUED)
    done = Scan(**AUTH, url=LONG, level=Level.AA, engines=["axe", "alfa"], status=ScanStatus.DONE,
                tool_versions={"axe-core": "4.13.0", "alfa": "0.84.2"},
                blocked_requests=["GET http://10.0.0.1/tracking.png — 10.0.0.1:80 resolves to a "
                                  "non-public address (10.0.0.1)"])
    aaa = Scan(**AUTH, url="https://www.example.org/", level=Level.AAA, engines=["axe", "alfa"],
               status=ScanStatus.DONE)
    failed = Scan(**AUTH, url="https://www.example.org/slow", level=Level.AA, engines=["axe"],
                  status=ScanStatus.ERROR, error="The check took too long and was stopped.")
    flags = {"US Social Security number": 1, "email address": 2}
    cleared = Scan(**AUTH, url="https://www.example.org/staff", level=Level.AA, engines=["axe"],
                   status=ScanStatus.DONE, pii_flags=flags, verified_by=USER,
                   verification_date=NOW)
    masked = Scan(**AUTH, url="https://www.example.org/records", level=Level.AA, engines=["axe"],
                  status=ScanStatus.DONE, pii_flags=flags)
    for scan in (queued, done, aaa, failed, cleared, masked):
        s.add(scan)
    s.commit()
    s.refresh(done)
    s.add(PrivateDataGrant(scan_id=cleared.id, granted_by=USER, granted_at=NOW, flags=flags))
    for scan in (cleared, masked):
        s.add(Finding(scan_id=scan.id, engine=Engine.AXE, outcome=Outcome.FAIL,
                      rule_id="label", sc="1.3.1,4.1.2", wcag_level="A",
                      selector="#staff-email", html_snippet='<input id="staff-email">',
                      message="Form element does not have a label", impact="critical",
                      profiles=["desktop"], fingerprint=f"p{scan.id}"))
    s.add(Finding(scan_id=done.id, engine=Engine.AXE, outcome=Outcome.FAIL, rule_id="image-alt",
                  sc="1.1.1", wcag_level="A", selector="body > main > img.hero",
                  html_snippet='<img src="hero.png"><script>alert(1)</script>',
                  message="Fix any of the following: Element does not have an alt attribute",
                  impact="critical", profiles=["desktop", "mobile-320"], fingerprint="a"))
    s.add(Finding(scan_id=done.id, engine=Engine.ALFA, outcome=Outcome.CANT_TELL, rule_id="sia-r14",
                  sc="2.5.3,4.1.2", wcag_level="A", selector="/html[1]/body[1]/main[1]/button[1]",
                  html_snippet='<button aria-label="Go">Search</button>', message="", impact=None,
                  profiles=["desktop"], fingerprint="b"))
    s.commit()
    many = Scan(**AUTH, url="https://www.example.org/gallery", level=Level.AA, engines=["axe"],
                status=ScanStatus.DONE)
    s.add(many)
    s.commit()
    s.refresh(many)
    for i in range(1, 8):
        s.add(Finding(scan_id=many.id, engine=Engine.AXE, outcome=Outcome.FAIL,
                      rule_id="image-alt", sc="1.1.1", wcag_level="A",
                      selector=f"main > ul.gallery > li:nth-child({i}) > img",
                      html_snippet=f'<img src="photo-{i}.jpg">',
                      message="Fix any of the following: Element does not have an alt attribute",
                      impact="critical", profiles=["desktop"], fingerprint=f"g{i}"))
    s.add(Finding(scan_id=many.id, engine=Engine.AXE, outcome=Outcome.CANT_TELL,
                  rule_id="link-in-text-block", sc="1.4.1", wcag_level="A",
                  selector="main > p > a", html_snippet='<a href="/more">more</a>', message="",
                  impact="serious", profiles=["desktop"], fingerprint="g8"))
    s.commit()
    for i in range(24):
        s.add(Scan(**AUTH, url=f"https://www.example.org/history/{i + 1}", level=Level.AA,
                   engines=["axe", "alfa"], status=ScanStatus.DONE))
    s.commit()
    for i in range(4):
        s.add(Scan(**AUTH, url=f"https://www.example.org/waiting/{i + 1}", level=Level.AA,
                   engines=["axe", "alfa"], status=ScanStatus.QUEUED))
    for item_id, status, sc, notes in (
        ("kbd-basics", ReviewStatus.FAIL, "2.1.1,2.1.3",
         "The search button can be reached with Tab but does nothing on Enter."),
        ("focus-visible", ReviewStatus.PASS, "2.4.7,2.4.13", ""),
        ("reflow", ReviewStatus.NEEDS_REVIEW, "1.4.10", "The data table scrolls sideways at 320px."),
    ):
        s.add(AssessmentResult(scan_id=done.id, checklist_id=CHECKLIST_ID,
                               checklist_version=int(checklist()["version"]), item_id=item_id,
                               sc=sc, status=status, reviewer=USER, reviewed_at=NOW, notes=notes))
    s.commit()
    me = create_user(s, USER, "selfscan-only-password", name="Self Scan")
    for sid in (2, 3, 4, *range(8, 32)):
        s.get(Scan, sid).created_by = me.id
    s.commit()
    for rule, outcome, sc, where, message in (
        ("aria-page-title", Outcome.PASS, "2.4.2", "", "The page has a title exposed to "
         "assistive technology."),
        ("aria-main-landmark", Outcome.PASS, "1.3.1,2.4.1", "", "The page exposes exactly one "
         "main landmark."),
        ("aria-heading-order", Outcome.CANT_TELL, "1.3.1", 'page › main › heading 3 "Results"',
         "Heading level 4 follows level 2, skipping a level. Check the outline makes sense."),
        ("aria-control-names", Outcome.FAIL, "1.3.1,4.1.2", "page › main › textbox 1",
         "This textbox has no accessible name, so a screen reader announces only its role. "
         "Give it a visible <label for>, or aria-labelledby pointing at visible text."),
    ):
        s.add(Finding(scan_id=done.id, engine=Engine.ARIA_TREE, outcome=outcome, rule_id=rule,
                      sc=sc, wcag_level="A", selector=where, html_snippet="", message=message,
                      profiles=["desktop"], fingerprint=f"sr-{rule}"))
    s.add(Finding(scan_id=many.id, engine=Engine.ARIA_TREE, outcome=Outcome.ERROR,
                  rule_id="aria-tree-not-run", advisory=True, message="The screen-reader "
                  "structure check could not run (accessibility tree unavailable). Nothing was "
                  "checked, so nothing here is a pass.", profiles=["desktop"], fingerprint="sr-x"))
    s.commit()
print("seeded 35 scans and 1 account")
