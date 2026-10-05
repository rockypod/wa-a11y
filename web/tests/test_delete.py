# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import re
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlmodel import Session, select
from starlette.testclient import TestClient

from app import main
from app.main import app
from app.store.db import get_engine
from app.store.models import (
    AssessmentResult,
    Engine,
    Finding,
    Level,
    Outcome,
    PrivateDataGrant,
    Prompt,
    ReviewStatus,
    Role,
    Scan,
    ScanDeletion,
    ScanStatus,
    Source,
    UrlStatus,
    User,
)

WEB = Path(__file__).parents[1]
ME = 1


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def add_user(uid: int, email: str, role: Role = Role.USER) -> User:
    fields = {"id": uid, "email": email, "role": role, "password_hash": "x"}
    with Session(get_engine()) as s:
        s.add(User(**fields))
        s.commit()
    return User(**fields)


@pytest.fixture
def other_user():
    return add_user(2, "other@example.com")


@pytest.fixture
def as_admin(monkeypatch):
    admin = add_user(3, "admin@example.com", Role.ADMIN)
    monkeypatch.setattr(main, "user_for_token", lambda _s, _t: admin)
    return admin


def add_scan(created_by=ME, **kw) -> int:
    fields = dict(
        url="https://example.org/private-path",
        level=Level.AA,
        engines=["axe"],
        profiles=["desktop"],
        status=ScanStatus.DONE,
        created_by=created_by,
    )
    with Session(get_engine()) as s:
        scan = Scan(**{**fields, **kw})
        s.add(scan)
        s.commit()
        return scan.id


def exists(scan_id: int) -> bool:
    with Session(get_engine()) as s:
        return s.get(Scan, scan_id) is not None


def token(client, path="/") -> str:
    return re.search(r'name="csrf" value="([^"]+)"', client.get(path).text).group(1)


def post_delete(client, scan_id, next_="/scans", csrf=True):
    data = {"next": next_}
    if csrf:
        data["csrf"] = token(client)
    return client.post(f"/scans/{scan_id}/delete", data=data)


def test_creator_sees_confirmation_and_can_delete(client):
    sid = add_scan()
    page = client.get(f"/scans/{sid}/delete")
    assert page.status_code == 200
    html = page.text
    assert f"Delete check {sid}?" in html
    assert "https://example.org/private-path" in html and "WCAG 2.2 Level AA" in html
    assert "cannot be undone" in html
    assert 'method="post"' in html and f'action="/scans/{sid}/delete"' in html
    assert 'name="csrf"' in html and ">Delete this check</button>" in html
    assert re.search(r'<a href="/scans" class="wa-standalone">Keep it</a>', html)
    assert "<script" not in html.lower()
    assert exists(sid)  # GET never deletes
    r = post_delete(client, sid)
    assert r.status_code == 303 and r.headers["location"] == f"/scans?deleted={sid}"
    assert not exists(sid)


@pytest.mark.usefixtures("other_user")
def test_other_user_cannot_delete(client):
    sid = add_scan(created_by=2)
    r = client.get(f"/scans/{sid}/delete")
    assert r.status_code == 403
    assert f"You cannot delete check {sid}" in r.text
    assert post_delete(client, sid).status_code == 403
    assert exists(sid)


def test_legacy_check_without_creator_is_admin_only(client, monkeypatch):
    sid = add_scan(created_by=None)
    assert client.get(f"/scans/{sid}/delete").status_code == 403
    assert post_delete(client, sid).status_code == 403
    assert exists(sid)
    admin = add_user(3, "admin@example.com", Role.ADMIN)
    monkeypatch.setattr(main, "user_for_token", lambda _s, _t: admin)
    assert client.get(f"/scans/{sid}/delete").status_code == 200
    assert post_delete(client, sid).status_code == 303
    assert not exists(sid)


@pytest.mark.usefixtures("other_user")
def test_admin_can_delete_anyones_check(client, as_admin):
    sid = add_scan(created_by=2)
    assert post_delete(client, sid).status_code == 303
    assert not exists(sid)
    with Session(get_engine()) as s:
        audit = s.exec(select(ScanDeletion)).one()
    assert audit.deleted_by == as_admin.email


@pytest.mark.parametrize("status", [ScanStatus.QUEUED, ScanStatus.RUNNING])
def test_waiting_or_running_check_is_refused_with_409(client, status):
    sid = add_scan(status=status)
    r = client.get(f"/scans/{sid}/delete")
    assert r.status_code == 409
    assert "can only be deleted once it has finished" in r.text
    assert post_delete(client, sid).status_code == 409
    assert exists(sid)


def test_missing_check_is_404(client):
    assert client.get("/scans/999/delete").status_code == 404
    assert post_delete(client, 999).status_code == 404


def test_post_without_valid_csrf_is_refused(client):
    sid = add_scan()
    r = post_delete(client, sid, csrf=False)
    assert r.status_code == 403
    assert "the form expired" in r.text and 'role="alert"' in r.text
    r = client.post(f"/scans/{sid}/delete", data={"csrf": "forged", "next": "/scans"})
    assert r.status_code == 403
    assert exists(sid)


def test_delete_cascades_and_keeps_a_minimal_audit_record(client):
    sid = add_scan()
    keep = add_scan()
    with Session(get_engine()) as s:
        f = Finding(
            scan_id=sid,
            engine=Engine.AXE,
            outcome=Outcome.FAIL,
            rule_id="image-alt",
            sc="1.1.1",
            fingerprint="fp",
            profiles=["desktop"],
        )
        s.add(f)
        s.commit()
        s.add(Prompt(scan_id=sid, finding_id=f.id, text="fix it"))
        s.add(PrivateDataGrant(scan_id=sid, granted_by="a@example.com", flags={"email": 1}))
        s.add(
            AssessmentResult(
                scan_id=sid,
                source=Source.GUIDED,
                checklist_id="c",
                checklist_version=1,
                item_id="i",
                status=ReviewStatus.PASS,
                reviewer="a@example.com",
            )
        )
        s.add(UrlStatus(url="https://example.org/", sc="1.1.1", latest_outcome=Outcome.FAIL,
                        last_scan_id=sid))  # fmt: skip
        s.commit()
    page = client.get(f"/scans/{sid}/delete").text
    assert "Tool results (problems, items to check by hand and passes): 1" in page
    assert "GitHub Copilot CLI requests: 1" in page
    assert "Assessment results recorded by a person: 1" in page

    assert post_delete(client, sid).status_code == 303
    with Session(get_engine()) as s:
        for model in (Finding, Prompt, PrivateDataGrant, AssessmentResult, UrlStatus):
            assert s.exec(select(model)).all() == [], model.__name__
        assert s.get(Scan, keep) is not None
        conn = s.connection()
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        audit = s.exec(select(ScanDeletion)).one()
        cols = {c["name"] for c in sa.inspect(conn).get_columns("scandeletion")}
    assert audit.scan_id == sid and audit.deleted_by == "tester@example.com"
    assert audit.deleted_at is not None
    assert cols == {"id", "scan_id", "deleted_by", "deleted_at", "rag_cleared"}


@pytest.mark.usefixtures("other_user")
def test_delete_links_only_where_allowed_and_unique(client):
    mine = add_scan()
    theirs = add_scan(created_by=2)
    legacy = add_scan(created_by=None)
    waiting = add_scan(status=ScanStatus.QUEUED)
    for path, back in (("/", "/"), ("/scans", "/scans")):
        html = client.get(path).text
        assert f'<a href="/scans/{mine}/delete?next={back}">Delete check {mine}</a>' in html
        for sid in (theirs, legacy, waiting):
            assert f"Delete check {sid}<" not in html
        assert f"Check {theirs}: https://example.org/private-path" in html


def test_keep_it_and_redirect_never_leave_the_site(client):
    sid = add_scan()
    for evil in ("//evil.example/", "https://evil.example/", "/\\evil.example", "/scans?page=0",
                 "/scans?page=2&x=//evil.example", "/settings"):  # fmt: skip
        html = client.get(f"/scans/{sid}/delete", params={"next": evil}).text
        assert '<a href="/scans" class="wa-standalone">Keep it</a>' in html, evil
        assert 'name="next" value="/scans"' in html
    r = post_delete(client, sid, next_="https://evil.example/")
    assert r.headers["location"] == f"/scans?deleted={sid}"


def test_return_to_home_and_status_message(client):
    sid = add_scan()
    html = client.get(f"/scans/{sid}/delete?next=/").text
    assert '<a href="/" class="wa-standalone">Keep it</a>' in html
    r = post_delete(client, sid, next_="/")
    assert r.headers["location"] == f"/?deleted={sid}"
    home = client.get(r.headers["location"]).text
    assert re.search(rf'role="status"[^>]*>\s*<p>Check {sid} was deleted.</p>', home)


def test_status_message_needs_a_real_deletion_by_you(client, monkeypatch):
    sid = add_scan()
    assert "was deleted" not in client.get(f"/scans?deleted={sid}").text
    assert "was deleted" not in client.get("/scans?deleted=abc").text
    post_delete(client, sid)
    assert f"Check {sid} was deleted." in client.get(f"/scans?deleted={sid}").text
    other = add_user(2, "other@example.com")
    monkeypatch.setattr(main, "user_for_token", lambda _s, _t: other)
    assert "was deleted" not in client.get(f"/scans?deleted={sid}").text


def test_paging_stays_valid_when_the_last_item_on_a_page_is_deleted(client):
    ids = [add_scan() for _ in range(26)]
    oldest = ids[0]
    page2 = client.get("/scans?page=2").text
    assert f'href="/scans/{oldest}/delete?next=/scans%3Fpage%3D2"' in page2
    html = client.get(f"/scans/{oldest}/delete?next=/scans%3Fpage%3D2").text
    assert 'href="/scans?page=2" class="wa-standalone">Keep it' in html
    r = post_delete(client, oldest, next_="/scans?page=2")
    assert r.headers["location"] == f"/scans?deleted={oldest}"
    assert client.get(r.headers["location"]).status_code == 200
    ids += [add_scan() for _ in range(3)]
    r = post_delete(client, ids[1], next_="/scans?page=2")
    assert r.headers["location"] == f"/scans?page=2&deleted={ids[1]}"
    page2 = client.get(r.headers["location"])
    assert page2.status_code == 200 and f"Check {ids[1]} was deleted." in page2.text


def test_new_check_records_its_creator(client, monkeypatch):
    from app import routes

    monkeypatch.setattr(routes, "check_scan_url", lambda url: url.strip())
    r = client.post(
        "/scans",
        data={
            "url": "https://example.org/",
            "level": "2.2-AA",
            "engines": "axe",
            "consent": "yes",
            "csrf": token(client),
        },
    )
    assert r.status_code == 303
    with Session(get_engine()) as s:
        assert s.exec(select(Scan)).one().created_by == ME


def _cfg(url: str) -> Config:
    cfg = Config(str(WEB / "alembic.ini"))
    cfg.set_main_option("script_location", str(WEB / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migration_from_3c7a91e2b4d8_keeps_existing_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "3c7a91e2b4d8")
    engine = sa.create_engine(url)
    with engine.begin() as c:
        c.exec_driver_sql("PRAGMA foreign_keys=ON")
        c.exec_driver_sql(
            "INSERT INTO scan (id, url, level, engines, profiles, status, tool_versions, "
            "blocked_requests, privacy_consent, automated_precheck, pii_flags, created_at) VALUES "
            "(7, 'https://example.org/', 'AA', '[\"axe\"]', '[\"desktop\"]', 'DONE', '{}', '[]', "
            "1, 1, '{}', '2026-10-01 00:00:00')"
        )
        c.exec_driver_sql(
            "INSERT INTO finding (id, scan_id, source, engine, outcome, advisory, rule_id, "
            "selector, html_snippet, message, profiles, fingerprint) VALUES "
            "(1, 7, 'AUTOMATED', 'AXE', 'FAIL', 0, 'image-alt', 'img', '', '', '[]', 'fp')"
        )
        c.exec_driver_sql("INSERT INTO prompt (id, scan_id, finding_id, text, created_at) "
                          "VALUES (1, 7, 1, 'fix', '2026-10-01 00:00:00')")  # fmt: skip
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT id, created_by FROM scan").fetchall() == [(7, None)]
        assert c.exec_driver_sql("SELECT count(*) FROM finding").scalar() == 1
        assert c.exec_driver_sql("SELECT count(*) FROM prompt").scalar() == 1
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert c.exec_driver_sql("SELECT count(*) FROM scandeletion").scalar() == 0
    # ON DELETE SET NULL: a removed account's checks become admin-only to delete
    with engine.begin() as c:
        c.exec_driver_sql("PRAGMA foreign_keys=ON")
        c.exec_driver_sql(
            "INSERT INTO user (id, email, name, password_hash, role, is_active, failed_logins, "
            "created_at) VALUES (5, 'a@example.com', '', 'x', 'USER', 1, 0, '2026-10-01')"
        )
        c.exec_driver_sql("UPDATE scan SET created_by = 5")
        c.exec_driver_sql("DELETE FROM user WHERE id = 5")
        assert c.exec_driver_sql("SELECT created_by FROM scan").scalar() is None
    command.downgrade(cfg, "3c7a91e2b4d8")
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT count(*) FROM finding").scalar() == 1
    engine.dispose()


def test_deleting_removes_the_check_from_the_rag_index(client, monkeypatch):
    from app import rag

    forgotten = []
    monkeypatch.setenv("WA_A11Y_RAG", "1")
    monkeypatch.setattr(rag, "forget_scan", forgotten.append)
    sid = add_scan()
    post_delete(client, sid)
    assert forgotten == [sid]


def test_rag_failure_never_undoes_the_deletion(client, monkeypatch):
    from app import rag

    def boom(_scan_id):
        raise RuntimeError("index unavailable")

    monkeypatch.setenv("WA_A11Y_RAG", "1")
    monkeypatch.setattr(rag, "forget_scan", boom)
    sid = add_scan()
    assert post_delete(client, sid).status_code == 303
    assert not exists(sid)


def test_failed_rag_cleanup_is_recorded_and_retried(client, monkeypatch):
    from app import deletion, rag

    monkeypatch.setenv("WA_A11Y_RAG", "1")
    monkeypatch.setattr(rag, "forget_scan", lambda _sid: (_ for _ in ()).throw(RuntimeError()))
    sid = add_scan()
    post_delete(client, sid)
    with Session(get_engine()) as s:
        record = s.exec(select(ScanDeletion).where(ScanDeletion.scan_id == sid)).one()
        assert record.rag_cleared is False
    retried = []
    monkeypatch.setattr(rag, "forget_scan", retried.append)
    assert deletion.retry_pending(get_engine()) == 1 and retried == [sid]
    with Session(get_engine()) as s:
        assert s.exec(select(ScanDeletion).where(ScanDeletion.scan_id == sid)).one().rag_cleared
    assert deletion.retry_pending(get_engine()) == 0


def test_successful_rag_cleanup_is_marked_cleared(client, monkeypatch):
    from app import rag

    monkeypatch.setenv("WA_A11Y_RAG", "1")
    monkeypatch.setattr(rag, "forget_scan", lambda _sid: None)
    sid = add_scan()
    post_delete(client, sid)
    with Session(get_engine()) as s:
        assert s.exec(select(ScanDeletion).where(ScanDeletion.scan_id == sid)).one().rag_cleared
