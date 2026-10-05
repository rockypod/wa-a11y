# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.assessment import results
from app.store.db import make_engine
from app.store.models import (
    AssessmentResult,
    Engine,
    Finding,
    Level,
    Outcome,
    Prompt,
    ReviewStatus,
    Scan,
    Source,
)

WEB = Path(__file__).parents[1]
M1_HEAD = "0106893a0156"


def _cfg(url: str) -> Config:
    cfg = Config(str(WEB / "alembic.ini"))
    cfg.set_main_option("script_location", str(WEB / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def m1_db(tmp_path):
    url = f"sqlite:///{tmp_path / 'm1.db'}"
    command.upgrade(_cfg(url), M1_HEAD)
    engine = make_engine(url)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO scan (id, url, level, engines, profiles, status, tool_versions, "
                "blocked_requests, privacy_consent, authorized_by, automated_precheck, pii_flags, "
                "created_at) VALUES (1, 'https://example.org/', 'AA', '[\"axe\", \"alfa\"]', "
                "'[\"desktop\"]', 'DONE', '{}', '[]', 1, 'tester@example.com', 1, "
                "'{\"email address\": 1}', '2026-10-01 10:00:00')"
            )
        )
        rows = [
            (1, "AXE", "FAIL", "image-alt", "1.1.1", "A", "img", "<img src=x>", "critical"),
            (2, "ALFA", "CANT_TELL", "sia-r14", "2.5.3,4.1.2", "A", "/html/body/button", "", None),
            (3, "AXE", "CANT_TELL", "color-contrast", "1.4.3", "AA", "p", "<p>x</p>", "serious"),
        ]
        for fid, eng, out, rule, sc, lvl, sel, html, impact in rows:
            c.execute(
                text(
                    "INSERT INTO finding (id, scan_id, engine, outcome, rule_id, sc, wcag_level, "
                    "selector, html_snippet, message, impact, profiles, fingerprint) VALUES "
                    "(:id, 1, :eng, :out, :rule, :sc, :lvl, :sel, :html, 'msg', :impact, "
                    "'[\"desktop\"]', :fp)"
                ),
                dict(
                    id=fid,
                    eng=eng,
                    out=out,
                    rule=rule,
                    sc=sc,
                    lvl=lvl,
                    sel=sel,
                    html=html,
                    impact=impact,
                    fp=f"fp-{fid}",
                ),
            )
        c.execute(
            text(
                "INSERT INTO prompt (id, scan_id, finding_id, text, created_at) "
                "VALUES (1, 1, 1, 'fix image-alt', '2026-10-01 10:01:00')"
            )
        )
        c.execute(
            text(
                "INSERT INTO urlstatus (id, url, sc, latest_outcome, last_scan_id) "
                "VALUES (1, 'https://example.org/', '1.1.1', 'FAIL', 1)"
            )
        )
    yield url, engine
    engine.dispose()


def _dump(engine, table: str, columns: str) -> list[tuple]:
    with engine.connect() as c:
        return [tuple(r) for r in c.execute(text(f"SELECT {columns} FROM {table} ORDER BY id"))]  # noqa: S608


M1_FINDING_COLUMNS = (
    "id, scan_id, engine, outcome, rule_id, sc, wcag_level, selector, html_snippet, message, "
    "impact, profiles, fingerprint"
)

M1_TABLES = [
    ("finding", M1_FINDING_COLUMNS),
    ("prompt", "id, scan_id, finding_id, text"),
    ("urlstatus", "id, url, sc, latest_outcome, last_scan_id"),
    ("scan", "id, url, status, pii_flags, authorized_by"),
]


def test_clean_db_has_the_unified_model(tmp_path):
    url = f"sqlite:///{tmp_path / 'clean.db'}"
    command.upgrade(_cfg(url), "head")
    engine = make_engine(url)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("finding")}
        assert {"source", "advisory", "engine", "outcome", "sc", "wcag_level"} <= cols
        assert "assessmentresult" in inspect(engine).get_table_names()
        command.check(_cfg(url))
    finally:
        engine.dispose()


def test_m1_rows_migrate_without_data_loss(m1_db):
    url, engine = m1_db
    before = {t: _dump(engine, t, cols) for t, cols in M1_TABLES}
    assert all(before.values())
    command.upgrade(_cfg(url), "head")
    # the finding rebuild must not cascade into prompts (data-loss guard)
    assert before == {t: _dump(engine, t, cols) for t, cols in M1_TABLES}
    with Session(engine) as s:
        found = {f.id: f for f in s.exec(select(Finding))}
    assert {f.source for f in found.values()} == {Source.AUTOMATED}
    assert found[1].engine is Engine.AXE and found[1].outcome is Outcome.FAIL
    assert found[2].engine is Engine.ALFA and found[2].outcome is Outcome.CANT_TELL
    assert not any(f.advisory for f in found.values())
    command.check(_cfg(url))


def test_m1_unmapped_rows_become_advisory_without_changing_outcome(m1_db):
    url, engine = m1_db
    with engine.begin() as c:
        c.execute(text("UPDATE finding SET sc = NULL, wcag_level = NULL WHERE id = 3"))
    command.upgrade(_cfg(url), "head")
    with Session(engine) as s:
        f = s.get(Finding, 3)
    assert f.advisory is True
    assert f.outcome is Outcome.CANT_TELL


def test_downgrade_to_m1_keeps_axe_and_alfa_rows(m1_db):
    url, engine = m1_db
    before = _dump(engine, "finding", M1_FINDING_COLUMNS)
    cfg = _cfg(url)
    command.upgrade(cfg, "head")
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO finding (scan_id, source, engine, outcome, advisory, rule_id, "
                "selector, html_snippet, message, profiles, fingerprint) VALUES (1, 'AUTOMATED', "
                "'FASTPASS', 'FAIL', 0, 'fp-rule', '', '', '', '[]', 'fp-x')"
            )
        )
    command.downgrade(cfg, M1_HEAD)
    assert _dump(engine, "finding", M1_FINDING_COLUMNS) == before
    assert "assessmentresult" not in inspect(engine).get_table_names()
    command.upgrade(cfg, "head")


def _scan(s: Session) -> Scan:
    scan = Scan(url="https://example.org/", level=Level.AA, engines=["axe", "alfa"])
    s.add(scan)
    s.commit()
    s.refresh(scan)
    return scan


def test_enums_serialise_to_contract_values(app_db):
    assert [e.value for e in Engine] == [
        "axe",
        "alfa",
        "accessibility-insights-fastpass",
        "aria-tree",
    ]
    assert [s.value for s in Source] == ["automated", "guided", "manual"]
    assert [s.value for s in ReviewStatus] == ["pass", "fail", "needs-review", "not-applicable"]


def test_finding_defaults_to_automated_and_round_trips(app_db):
    engine = make_engine(app_db)
    with Session(engine) as s:
        scan = _scan(s)
        f = Finding(
            scan_id=scan.id,
            engine=Engine.FASTPASS,
            outcome=Outcome.FAIL,
            rule_id="focus-indicator",
            sc="2.4.7",
            wcag_level="AA",
            fingerprint="fp",
        )
        s.add(f)
        s.commit()
        s.refresh(f)
        dumped = f.model_dump(mode="json")
    engine.dispose()
    assert dumped["source"] == "automated"
    assert dumped["engine"] == "accessibility-insights-fastpass"
    assert dumped["advisory"] is False


def test_assessment_result_storage(app_db):
    engine = make_engine(app_db)
    with Session(engine) as s:
        scan = _scan(s)
        r = AssessmentResult(
            scan_id=scan.id,
            checklist_id="wa-a11y-assessment",
            checklist_version=1,
            item_id="kbd-basics",
            sc="2.1.1,2.1.3",
            status=ReviewStatus.NEEDS_REVIEW,
            reviewer="tester@example.com",
            notes="Menu opens on hover only.",
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        assert r.source is Source.GUIDED
        assert r.reviewed_at is not None
        assert r.model_dump(mode="json")["status"] == "needs-review"
        s.add(
            AssessmentResult(
                scan_id=scan.id,
                checklist_id="wa-a11y-assessment",
                checklist_version=1,
                item_id="kbd-basics",
                status=ReviewStatus.PASS,
                reviewer="other@example.com",
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        s.exec(text("DELETE FROM scan WHERE id = :id").bindparams(id=scan.id))
        s.commit()
        assert s.exec(select(AssessmentResult)).all() == []
    engine.dispose()


def test_prompt_rows_survive_the_migration(m1_db):
    url, engine = m1_db
    command.upgrade(_cfg(url), "head")
    with Session(engine) as s:
        assert [p.finding_id for p in s.exec(select(Prompt))] == [1]


def test_record_stores_checklist_provenance_and_replaces_on_rereview(app_db):
    engine = make_engine(app_db)
    with Session(engine) as s:
        scan = _scan(s)
        first = results.record(s, scan, "kbd-basics", ReviewStatus.FAIL, " tester@example.com ")
        again = results.record(
            s, scan, "kbd-basics", ReviewStatus.PASS, "tester@example.com", "fixed"
        )
        rows = s.exec(select(AssessmentResult)).all()
    engine.dispose()
    assert first.id == again.id and len(rows) == 1
    r = rows[0]
    assert (r.source, r.checklist_id, r.item_id) == (
        Source.GUIDED,
        "wa-a11y-assessment",
        "kbd-basics",
    )
    assert r.checklist_version == results.checklist()["version"]
    assert r.sc == "2.1.1,2.1.3" and r.advisory is False
    assert (r.status, r.reviewer, r.notes) == (ReviewStatus.PASS, "tester@example.com", "fixed")


def test_record_rejects_bad_input(app_db):
    engine = make_engine(app_db)
    with Session(engine) as s:
        scan = _scan(s)
        with pytest.raises(ValueError, match="unknown"):
            results.record(s, scan, "no-such-item", ReviewStatus.PASS, "tester@example.com")
        with pytest.raises(ValueError, match="reviewer"):
            results.record(s, scan, "kbd-basics", ReviewStatus.PASS, "  ")
        with pytest.raises(ValueError, match="never automated"):
            results.record(
                s, scan, "kbd-basics", ReviewStatus.PASS, "t@example.com", source=Source.AUTOMATED
            )
        assert s.exec(select(AssessmentResult)).all() == []
    engine.dispose()


def test_record_bounds_notes_and_flags_private_data(app_db):
    mail = "jane.doe" + "@" + "dept.invalid"  # no personal-looking address in git (pii-scan)
    engine = make_engine(app_db)
    with Session(engine) as s:
        scan = _scan(s)
        r = results.record(
            s, scan, "kbd-basics", ReviewStatus.FAIL, "t@example.com", f"{mail} " + "n" * 9000
        )
        assert len(r.notes) == results.NOTES_MAX
        s.refresh(scan)
        assert scan.pii_flags == {"email address": 1}  # kinds and counts only, never the values
        assert mail not in str(scan.pii_flags)
        results.record(s, scan, "kbd-basics", ReviewStatus.FAIL, "t@example.com", "clean")
        s.refresh(scan)
        assert scan.pii_flags == {}
    engine.dispose()
