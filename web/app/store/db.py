# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

DEFAULT_DB_URL = "sqlite:////data/wa_a11y.db"

PRAGMAS = {
    "journal_mode": "WAL",
    "busy_timeout": "5000",
    "foreign_keys": "ON",
    "synchronous": "NORMAL",
}


def db_url() -> str:
    return os.environ.get("WA_A11Y_DB_URL", DEFAULT_DB_URL)


def make_engine(url: str | None = None) -> Engine:
    engine = create_engine(url or db_url(), connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001 — DB-API connection
        cur = dbapi_conn.cursor()
        for name, value in PRAGMAS.items():
            cur.execute(f"PRAGMA {name}={value}")
        cur.close()

    return engine


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
