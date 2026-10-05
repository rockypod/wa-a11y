# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select
from starlette.testclient import TestClient

from app import accounts, routes
from app.main import app
from app.store.db import get_engine
from app.store.models import AuthSession, Role, Scan, User

pytestmark = pytest.mark.real_auth
PW = "correct horse battery staple"  # noqa: S105


def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def make_user(email="ana@example.com", password=PW, active=True):
    with Session(get_engine()) as s:
        u = accounts.create_user(s, email, password, Role.USER, "Ana")
        u.is_active = active
        s.add(u)
        s.commit()
        return u.id


def csrf(c, path="/login"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(path).text).group(1)


def sign_in(c, email="ana@example.com", password=PW, nxt="/"):
    return c.post(
        "/login", data={"csrf": csrf(c), "email": email, "password": password, "next": nxt}
    )


def test_pages_require_sign_in_but_public_paths_stay_open():
    c = client()
    r = c.get("/scans/1?x=1")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Fscans%2F1%3Fx%3D1"
    assert c.get("/healthz").status_code == 200
    assert c.get("/login").status_code == 200


def test_login_page_is_accessible_authentication():
    make_user()
    html = client().get("/login").text
    assert 'autocomplete="username"' in html and 'autocomplete="current-password"' in html
    assert "paste your password" in html and "captcha" not in html.lower()
    assert "<script" not in html.lower()


def test_no_accounts_yet_explains_how_to_create_one():
    assert "python -m app.accounts create" in client().get("/login").text


def test_sign_in_sets_secure_cookie_and_stores_only_a_hash():
    make_user()
    c = client()
    r = sign_in(c, nxt="/help")
    assert r.status_code == 303 and r.headers["location"] == "/help"
    cookie = r.headers["set-cookie"]
    assert "wa_a11y_auth=" in cookie
    for flag in ("httponly", "secure", "samesite=strict"):
        assert flag in cookie.lower()
    token = re.search(r"wa_a11y_auth=([^;]+)", cookie).group(1)
    with Session(get_engine()) as s:
        stored = s.exec(select(AuthSession)).one()
    assert stored.token_hash != token and len(stored.token_hash) == 64
    page = c.get("/")
    assert (
        page.status_code == 200 and "Signed in as" in page.text and "ana@example.com" in page.text
    )
    assert "Signed in as <strong>Ana</strong>" in page.text


def test_failures_look_identical_and_keep_the_email():
    make_user()
    wrong = sign_in(client(), password="not the password!!")  # noqa: S106
    unknown = sign_in(client(), email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    msg = "The email address or password is not right"
    assert msg in wrong.text and msg in unknown.text
    assert 'value="ana@example.com"' in wrong.text


def test_lockout_after_repeated_failures_then_unlock():
    uid = make_user()
    for _ in range(accounts.MAX_FAILED):
        assert sign_in(client(), password="wrong password here").status_code == 401  # noqa: S106
    assert sign_in(client()).status_code == 401  # locked, even with the right password
    with Session(get_engine()) as s:
        u = s.get(User, uid)
        u.locked_until = datetime.now(UTC) - timedelta(seconds=1)
        s.add(u)
        s.commit()
    assert sign_in(client()).status_code == 303


@pytest.mark.parametrize(
    "nxt", ["//evil.example/x", "https://evil.example/", "\\\\evil", "javascript:alert(1)"]
)
def test_no_open_redirect(nxt):
    make_user()
    assert sign_in(client(), nxt=nxt).headers["location"] == "/"


def test_sign_out_revokes_the_session():
    make_user()
    c = client()
    sign_in(c)
    token = c.cookies.get("wa_a11y_auth")
    r = c.post("/logout", data={"csrf": csrf(c, "/help")})
    assert r.status_code == 303 and r.headers["location"] == "/login"
    c2 = client()
    c2.cookies.set("wa_a11y_auth", token)
    assert c2.get("/").status_code == 303  # the old token is dead server-side


def test_disabled_account_cannot_sign_in_or_keep_session():
    uid = make_user()
    c = client()
    sign_in(c)
    with Session(get_engine()) as s:
        u = s.get(User, uid)
        u.is_active = False
        s.add(u)
        s.commit()
    assert c.get("/").status_code == 303
    assert sign_in(client()).status_code == 401


def test_per_user_scan_limit_is_server_side(monkeypatch):
    monkeypatch.setattr(routes, "check_scan_url", lambda u: u)
    monkeypatch.setenv("WA_A11Y_MAX_QUEUED", "1000")
    make_user()
    c = client()
    sign_in(c)
    codes = []
    for _ in range(routes.RATE_LIMIT + 1):
        token = csrf(c, "/")
        codes.append(
            c.post(
                "/scans",
                data={
                    "csrf": token,
                    "url": "https://example.org/",
                    "level": "2.2-AA",
                    "engines": "axe",
                    "consent": "yes",
                },
            ).status_code
        )
        c.cookies.delete("session_")
    assert codes[-1] == 429 and codes.count(303) == routes.RATE_LIMIT
    with Session(get_engine()) as s:
        assert {sc.requested_by for sc in s.exec(select(Scan))} == {"ana@example.com"}


def test_password_rule_and_cli(monkeypatch, capsys):
    with Session(get_engine()) as s, pytest.raises(ValueError, match="at least 12"):
        accounts.create_user(s, "x@example.com", "short")
    pw = iter([PW, PW])
    monkeypatch.setattr(accounts.getpass, "getpass", lambda _prompt: next(pw))
    assert accounts.main(["create", "admin@example.com", "--admin"]) == 0
    assert accounts.main(["list"]) == 0
    assert "admin@example.com\tadmin\tactive" in capsys.readouterr().out


def test_failed_sign_in_marks_the_field_and_links_its_message():
    make_user()
    html = sign_in(client(), password="wrong password here").text  # noqa: S106
    assert 'id="error-summary"' in html and 'href="#email"' in html
    email = re.search(r'<input[^>]*id="email"[^>]*>', html).group(0)
    assert 'aria-describedby="email-error"' in email and 'aria-invalid="true"' in email
    assert "is-invalid" in email
    assert 'id="email-error" class="invalid-feedback"' in html
    assert html.lstrip().lower().startswith("<!doctype html>")


def test_accounts_cli_prints_usage_and_fails_on_bad_arguments():
    import pytest

    from app import accounts

    with pytest.raises(SystemExit) as stop:
        accounts.main([])
    assert "Usage:" in str(stop.value.code) and "create <email>" in str(stop.value.code)
