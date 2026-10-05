# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

# Session secret from the environment only: FastHTML must never write a .sesskey file

import mimetypes
import os
import re
import secrets
import stat
from pathlib import Path
from urllib.parse import quote

from fasthtml.common import (
    Meta,
    Style,
    fast_app,
)
from sqlmodel import Session
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from app import routes
from app.accounts import user_for_token
from app.assessment import pages as assessment_pages
from app.jobs import Runner, runner_enabled
from app.security import SecurityHeaders
from app.settings import COOKIE, Display
from app.statement import register as register_statement
from app.store.db import db_url as db_url_setting
from app.store.db import get_engine
from app.theme import fonts_dir, theme_css
from app.ui import AUTH_COOKIE, current_path, current_session, current_user, u

SECRET_ENV = "WA_A11Y_SESSION_SECRET"  # noqa: S105 — env var *name*, not a secret


PLACEHOLDER_SECRETS = {"", "change-me"}
MIN_SECRET_LEN = 32
PERSISTED_SECRET = re.compile(r"[0-9a-f]{64}\Z")


def _secret_file() -> Path:
    db_url = db_url_setting()
    if not db_url.startswith("sqlite:///"):
        raise RuntimeError(f"Set {SECRET_ENV} to a long random value (32+ characters).")
    return Path(db_url.removeprefix("sqlite:///")).parent / "session-secret"


def _session_secret() -> str:
    secret = os.environ.get(SECRET_ENV, "").strip()
    if secret not in PLACEHOLDER_SECRETS:
        # Security: a short secret makes session cookies guessable.
        if len(secret) < MIN_SECRET_LEN:
            raise RuntimeError(
                f"{SECRET_ENV} is too short: use {MIN_SECRET_LEN}+ random characters."
            )
        return secret
    # Not set, or still the example placeholder: generate one on first start and keep it on the
    # data volume, so sessions survive restarts and nobody runs with a guessable secret.
    path = _secret_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None:
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"{path} must be a regular file with mode 0600.")
        if metadata.st_mode & 0o077:
            raise RuntimeError(f"{path} permissions are too open; set mode 0600.")
        try:
            persisted = path.read_text(encoding="ascii")
        except UnicodeDecodeError:
            persisted = ""
        if PERSISTED_SECRET.fullmatch(persisted):
            return persisted

    temporary = path.with_name(f".{path.name}.{secrets.token_hex(16)}.tmp")
    value = secrets.token_hex(32)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            fd = -1
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if fd != -1:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return value


async def lifespan(_app):
    runner = Runner() if runner_enabled() else None
    if runner:
        runner.start()
    try:
        yield
    finally:
        if runner:
            runner.stop()


PUBLIC_PATHS = ("/login", "/healthz", "/static/")


async def require_login(req, session):
    # Every page needs a signed-in user except sign-in, health and fonts
    path = req.scope.get("path", "/")
    current_path.set(path)
    if path.startswith(PUBLIC_PATHS):
        return None
    with Session(get_engine()) as s:
        user = user_for_token(s, req.cookies.get(AUTH_COOKIE))
        if user is not None and user in s:
            s.expunge(user)
    if user is None:
        nxt = path + (f"?{req.url.query}" if req.url.query else "")
        return RedirectResponse(u(f"/login?next={quote(nxt, safe='')}"), status_code=303)
    req.scope["user"] = user
    current_user.set(user)
    current_session.set(session)
    return None


def apply_display_settings(req):
    req.htmlkw.update(Display.from_cookie(req.cookies.get(COOKIE)).html_attrs())


app, rt = fast_app(
    pico=False,
    default_hdrs=False,
    surreal=False,
    htmx=False,
    live=False,
    secret_key=_session_secret(),
    sess_https_only=True,
    same_site="strict",
    # Own cookie name and path: other apps on a shared domain never receive it
    session_cookie="wa_a11y_session",
    sess_path=os.environ.get("WA_A11Y_BASE_PATH", "").rstrip("/") or "/",
    max_age=12 * 3600,
    hdrs=(
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Style(theme_css()),
    ),
    htmlkw={"lang": "en"},
    # Off: it echoes the request Host header into <link rel=canonical>.
    canonical=False,
    lifespan=lifespan,
    before=[require_login, apply_display_settings],
    # Dedicated public folder: FastHTML's catch-all static route must never expose project files
    static_path=str(Path(__file__).parent / "public"),
)


routes.register(rt)
assessment_pages.register(rt)
register_statement(rt)

app.add_middleware(SecurityHeaders)
mimetypes.add_type("font/woff2", ".woff2")

if (_fonts := fonts_dir()) is not None:
    app.router.routes.insert(
        0, Mount("/static/fonts", app=StaticFiles(directory=_fonts), name="fonts")
    )


@rt("/healthz")
def healthz():
    return PlainTextResponse("ok")
