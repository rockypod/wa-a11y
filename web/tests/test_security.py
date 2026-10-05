# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import base64
import hashlib
import re

from sqlmodel import Session
from starlette.testclient import TestClient

from app import routes
from app.main import app
from app.privacy import Authorization
from app.store.db import get_engine
from app.store.models import Level, Scan, ScanStatus


def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_security_headers_on_every_response():
    c = client()
    for path in ("/", "/help", "/settings", "/healthz", "/scans/999", "/nope"):
        h = c.get(path).headers
        assert "script-src 'none'" in h["content-security-policy"], path
        assert "'unsafe-inline'" not in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        assert "camera=()" in h["permissions-policy"]


def test_csp_hash_matches_the_exact_inline_style():
    r = client().get("/")
    inline = re.search(r"<style>(.*?)</style>", r.text, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(inline.encode()).digest()).decode()
    assert f"style-src 'sha256-{digest}'" in r.headers["content-security-policy"]
    assert r.text.count("<style>") == 1
    assert ' style="' not in r.text  # style attributes are blocked by the CSP too


def _post(c, **data):
    token = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text).group(1)
    return c.post(
        "/scans",
        data={
            "csrf": token,
            "url": "https://example.org/",
            "level": "2.2-AA",
            "engines": "axe",
            "consent": "yes",
            **data,
        },
    )


def test_queue_full_returns_503_and_keeps_input(monkeypatch):
    monkeypatch.setattr(routes, "check_scan_url", lambda u: u)
    monkeypatch.setenv("WA_A11Y_MAX_QUEUED", "2")
    with Session(get_engine()) as s:
        for _ in range(2):
            s.add(
                Scan(
                    url="https://x.org/", level=Level.AA, engines=["axe"], status=ScanStatus.QUEUED
                )
            )
        s.commit()
    r = _post(client())
    assert r.status_code == 503
    assert "busy right now" in r.text and 'value="https://example.org/"' in r.text


def test_per_session_rate_limit(monkeypatch):
    monkeypatch.setattr(routes, "check_scan_url", lambda u: u)
    monkeypatch.setenv("WA_A11Y_MAX_QUEUED", "1000")
    c = client()
    codes = [_post(c).status_code for _ in range(routes.RATE_LIMIT + 1)]
    assert codes[: routes.RATE_LIMIT] == [303] * routes.RATE_LIMIT
    assert codes[-1] == 429


def test_oversized_form_is_refused_before_parsing():
    c = client()
    r = c.post(
        "/scans",
        content=b"url=" + b"x" * 20_000,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 413
    r = c.post(
        "/settings",
        content=b"font=" + b"x" * 20_000,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 413


def test_queue_cap_holds_under_concurrency(monkeypatch):
    import threading

    from app import jobs

    monkeypatch.setenv("WA_A11Y_MAX_QUEUED", "5")
    results = []

    def worker():
        with Session(get_engine()) as s:
            try:
                jobs.enqueue(
                    s,
                    "https://x.org/",
                    Level.AA,
                    ["axe"],
                    authorization=Authorization(True, "t@example.com"),
                )
                results.append("ok")
            except jobs.QueueFull:
                results.append("full")

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 5 and results.count("full") == 15


def test_session_secret_is_generated_when_missing_or_placeholder(monkeypatch, tmp_path):
    from app import main

    monkeypatch.setenv("WA_A11Y_DB_URL", f"sqlite:///{tmp_path}/wa_a11y.db")
    for value in ("", "change-me"):
        monkeypatch.setenv("WA_A11Y_SESSION_SECRET", value)
        first = main._session_secret()
        assert len(first) == 64 and first == main._session_secret()  # stable across restarts
    stored = tmp_path / "session-secret"
    assert stored.read_text() == first and oct(stored.stat().st_mode & 0o777) == "0o600"


def test_session_secret_reuses_valid_persisted_file(monkeypatch, tmp_path):
    from app import main

    monkeypatch.setenv("WA_A11Y_DB_URL", f"sqlite:///{tmp_path}/wa_a11y.db")
    monkeypatch.setenv("WA_A11Y_SESSION_SECRET", "")
    stored = tmp_path / "session-secret"
    value = "a" * 64
    stored.write_text(value)
    stored.chmod(0o600)

    assert main._session_secret() == value


def test_session_secret_regenerates_empty_or_short_file(monkeypatch, tmp_path):
    from app import main

    monkeypatch.setenv("WA_A11Y_DB_URL", f"sqlite:///{tmp_path}/wa_a11y.db")
    monkeypatch.setenv("WA_A11Y_SESSION_SECRET", "")
    stored = tmp_path / "session-secret"
    for invalid in ("", "a" * 63):
        stored.write_text(invalid)
        stored.chmod(0o600)
        value = main._session_secret()
        assert len(value) == 64 and value != invalid
        assert stored.read_text() == value


def test_session_secret_refuses_open_permissions(monkeypatch, tmp_path):
    import pytest

    from app import main

    monkeypatch.setenv("WA_A11Y_DB_URL", f"sqlite:///{tmp_path}/wa_a11y.db")
    monkeypatch.setenv("WA_A11Y_SESSION_SECRET", "")
    stored = tmp_path / "session-secret"
    stored.write_text("a" * 64)
    stored.chmod(0o640)

    with pytest.raises(RuntimeError, match="permissions are too open"):
        main._session_secret()


def test_short_session_secret_is_refused(monkeypatch):
    import pytest

    from app import main

    monkeypatch.setenv("WA_A11Y_SESSION_SECRET", "too-short")
    with pytest.raises(RuntimeError, match="too short"):
        main._session_secret()
