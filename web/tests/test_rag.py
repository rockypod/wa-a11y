# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import pytest
from sqlmodel import Session

from app import rag
from app.store.db import get_engine
from app.store.models import Engine, Finding, Level, Outcome, Scan, ScanStatus

FINDINGS = [
    (
        "image-alt",
        "1.1.1",
        "Element does not have an alt attribute",
        "img.hero",
        '<img src="hero.jpg">',
    ),
    (
        "color-contrast-enhanced",
        "1.4.6",
        "Element has insufficient color contrast of 4.6 (foreground #767676, background #ffffff)",
        "p.note",
        '<p class="note">Office hours</p>',
    ),
    (
        "label",
        "1.3.1,4.1.2",
        "Form element does not have an implicit (wrapped) <label> or explicit label",
        "#zip",
        '<input id="zip" type="text">',
    ),
    (
        "link-name",
        "2.4.4,4.1.2",
        "Element does not have text that is visible to screen readers",
        "a.social",
        '<a class="social" href="/x"><svg></svg></a>',
    ),
]
GOLDEN = [
    ("pictures without alternative text", "image-alt"),
    ("text is too light against the background", "color-contrast-enhanced"),
    ("input field is missing a label", "label"),
    ("icon link has no accessible name", "link-name"),
]


@pytest.fixture
def chroma(tmp_path, monkeypatch):
    monkeypatch.setenv("WA_A11Y_CHROMA_PATH", str(tmp_path / "chroma"))
    yield


def make_scan(rules, url="https://www.example.org/", level=Level.AAA):
    with Session(get_engine()) as s:
        scan = Scan(url=url, level=level, engines=["axe"], status=ScanStatus.DONE)
        s.add(scan)
        s.commit()
        s.refresh(scan)
        fs = []
        for rule, sc, msg, sel, html in FINDINGS:
            if rule not in rules:
                continue
            f = Finding(
                scan_id=scan.id,
                engine=Engine.AXE,
                outcome=Outcome.FAIL,
                rule_id=rule,
                sc=sc,
                wcag_level="A",
                selector=sel,
                html_snippet=html,
                message=msg,
                impact="serious",
                profiles=["desktop"],
                fingerprint=f"fp-{rule}",
            )
            s.add(f)
            fs.append(f)
        s.commit()
        for f in fs:
            s.refresh(f)
        s.refresh(scan)
        s.expunge_all()
        return scan, fs


def rules_of(hits):
    return [h["metadata"]["rule_id"] for h in hits]


def test_golden_queries_find_the_right_problem_first(chroma):
    scan, fs = make_scan({r[0] for r in FINDINGS})
    assert rag.index_scan(scan, fs) == 4
    for question, expected in GOLDEN:
        top = rules_of(rag.search("findings", question, k=3))
        assert top[0] == expected, f"{question!r} → {top}"


def test_rescan_upserts_and_marks_vanished_findings_fixed(chroma):
    scan1, fs1 = make_scan({"image-alt", "label"})
    rag.index_scan(scan1, fs1)
    scan2, fs2 = make_scan({"label"})
    rag.index_scan(scan2, fs2)
    col = rag.collection("findings")
    assert col.count() == 2
    open_ = rules_of(rag.search("findings", "problem", where={"status": "open"}))
    fixed = rules_of(rag.search("findings", "problem", where={"status": "fixed"}))
    assert open_ == ["label"] and fixed == ["image-alt"]


def test_forget_scan_removes_its_entries_and_reopens_what_it_marked_fixed(chroma):
    scan1, fs1 = make_scan({"image-alt", "label"})
    rag.index_scan(scan1, fs1)
    scan2, fs2 = make_scan({"label"})
    rag.index_scan(scan2, fs2)
    assert rag.forget_scan(scan2.id) == 2
    col = rag.collection("findings")
    left = col.get(include=["metadatas"])
    assert [m["rule_id"] for m in left["metadatas"]] == ["image-alt"]
    meta = left["metadatas"][0]
    assert meta["status"] == "open" and meta["scan_id"] == scan1.id
    assert "fixed_in_scan" not in meta
    assert rules_of(rag.search("findings", "missing alt text", where={"status": "open"})) == [
        "image-alt"
    ]
    assert rag.forget_scan(scan2.id) == 0


def test_levels_are_kept_apart(chroma):
    aa, fa = make_scan({"image-alt"}, level=Level.AA)
    aaa, fb = make_scan({"image-alt"}, level=Level.AAA)
    rag.index_scan(aa, fa)
    rag.index_scan(aaa, fb)
    assert rag.collection("findings").count() == 2


def test_guidance_and_reindex_from_sqlite(chroma):
    scan, fs = make_scan({r[0] for r in FINDINGS})
    rag.index_scan(scan, fs)
    before = rules_of(rag.search("findings", "missing alt text"))
    findings, guidance = rag.reindex(get_engine())
    assert findings == 4 and guidance >= 86
    assert rules_of(rag.search("findings", "missing alt text")) == before
    g = rag.search("guidance", "how big should buttons be", k=3)
    assert any(h["metadata"]["sc"] in {"2.5.5", "2.5.8"} for h in g)


def test_chroma_is_embedded_only():
    # ChromaDB advisories are server-mode only: no HTTP client/server, auth or remote code
    from pathlib import Path

    src = "\n".join(p.read_text() for p in (Path(rag.__file__).parent).glob("*.py"))
    for forbidden in (
        "HttpClient",
        "AsyncHttpClient",
        "chroma_server",
        "trust_remote_code",
        "chroma_client_auth",
        "chroma_server_auth",
        "SentenceTransformer",
    ):
        assert forbidden not in src, forbidden
    assert "PersistentClient" in src and "anonymized_telemetry=False" in src
