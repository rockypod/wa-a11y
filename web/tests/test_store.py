# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.store.backup import backup
from app.store.db import make_engine
from app.store.models import Engine, Finding, Level, Outcome, Scan, ScanStatus

WEB = Path(__file__).parents[1]
TABLES = {"scan", "finding", "prompt", "urlstatus", "alembic_version"}


def alembic_cfg(url: str) -> Config:
    cfg = Config(str(WEB / "alembic.ini"))
    cfg.set_main_option("script_location", str(WEB / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def db(tmp_path):
    url = f"sqlite:///{tmp_path / 'wa.db'}"
    command.upgrade(alembic_cfg(url), "head")
    engine = make_engine(url)
    yield url, engine
    engine.dispose()


def test_upgrade_fresh_db_creates_all_tables(db):
    _, engine = db
    assert TABLES <= set(inspect(engine).get_table_names())


def test_upgrade_existing_db_is_idempotent_and_reversible(db):
    url, engine = db
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    command.upgrade(cfg, "head")
    assert TABLES <= set(inspect(engine).get_table_names())


def test_models_and_migrations_have_not_drifted(db):
    url, _ = db
    command.check(alembic_cfg(url))


def test_pragmas_applied_on_connect(db):
    _, engine = db
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert c.execute(text("PRAGMA synchronous")).scalar() == 1


def _scan(session: Session) -> Scan:
    scan = Scan(url="https://example.org/", level=Level.AAA, engines=["axe", "alfa"])
    session.add(scan)
    session.commit()
    session.refresh(scan)
    return scan


def test_outcomes_are_stored_distinctly(db):
    _, engine = db
    with Session(engine) as s:
        scan = _scan(s)
        assert scan.status is ScanStatus.QUEUED
        for i, outcome in enumerate(Outcome):
            s.add(
                Finding(
                    scan_id=scan.id,
                    engine=Engine.AXE if i % 2 else Engine.ALFA,
                    outcome=outcome,
                    rule_id=f"rule-{i}",
                    fingerprint=f"fp-{i}",
                )
            )
        s.commit()
        stored = {f.outcome for f in s.exec(select(Finding))}
    assert stored == set(Outcome)


def test_deleting_scan_cascades_to_findings(db):
    _, engine = db
    with Session(engine) as s:
        scan = _scan(s)
        s.add(
            Finding(
                scan_id=scan.id,
                engine=Engine.AXE,
                outcome=Outcome.FAIL,
                rule_id="image-alt",
                fingerprint="fp",
            )
        )
        s.commit()
        s.exec(text("DELETE FROM scan WHERE id = :id").bindparams(id=scan.id))
        s.commit()
        assert s.exec(select(Finding)).all() == []


def test_foreign_keys_enforced(db):
    _, engine = db
    with Session(engine) as s:
        s.add(
            Finding(
                scan_id=999, engine=Engine.AXE, outcome=Outcome.FAIL, rule_id="x", fingerprint="fp"
            )
        )
        with pytest.raises(Exception, match="FOREIGN KEY"):
            s.commit()


def test_online_backup_while_app_holds_connection(db, tmp_path):
    url, engine = db
    src = Path(url.removeprefix("sqlite:///"))
    with Session(engine) as s:
        _scan(s)
        _scan(s)
        dest = backup(tmp_path / "backups" / "copy.db", src=src)
    with sqlite3.connect(dest) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("SELECT count(*) FROM scan").fetchone()[0] == 2
