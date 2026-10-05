# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import os
from pathlib import Path

import pytest

# Throwaway value for tests only; the real secret comes from the environment (.env).
os.environ.setdefault("WA_A11Y_SESSION_SECRET", "test-only-not-a-secret-padded-to-32-chars")
os.environ.setdefault("WA_A11Y_RUNNER", "0")
os.environ.setdefault("WA_A11Y_WAIT_S", "0")
os.environ.setdefault("WA_A11Y_RAG", "0")

_css = Path(__file__).parent / "fixtures" / "theme.css"
os.environ.setdefault("WA_A11Y_CSS", str(_css))
_fonts = Path(__file__).parents[2] / "styles" / "dist" / "fonts"
if _fonts.is_dir():
    os.environ.setdefault("WA_A11Y_FONTS", str(_fonts))


@pytest.fixture(autouse=True)
def app_db(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    from app.store import db

    url = f"sqlite:///{tmp_path / 'app.db'}"
    web = Path(__file__).parents[1]
    cfg = Config(str(web / "alembic.ini"))
    cfg.set_main_option("script_location", str(web / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    monkeypatch.setenv("WA_A11Y_DB_URL", url)
    monkeypatch.setattr(db, "_engine", None)
    yield url
    if db._engine is not None:
        db._engine.dispose()


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: use the real sign-in flow (no auto sign-in)")


@pytest.fixture(autouse=True)
def signed_in(request, monkeypatch, app_db):
    if request.node.get_closest_marker("real_auth"):
        return None
    from sqlmodel import Session

    from app import main
    from app.store.db import get_engine
    from app.store.models import Role, User

    fields = {"id": 1, "email": "tester@example.com", "role": Role.USER, "password_hash": "x"}
    with Session(get_engine()) as s:
        s.add(User(**fields))
        s.commit()
    user = User(**fields)
    monkeypatch.setattr(main, "user_for_token", lambda _session, _token: user)
    return user
