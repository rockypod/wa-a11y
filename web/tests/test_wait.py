# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

# WCAG 2.2 SC 3.2.5: no timer, refresh or script; the page changes only on request

import asyncio
import re
import threading
import time

import pytest
from sqlmodel import Session, select
from starlette.testclient import TestClient

from app import jobs, routes
from app.main import app
from app.store.db import get_engine
from app.store.models import Level, Scan, ScanStatus


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


@pytest.fixture
def wait(monkeypatch):
    def set_(seconds, waiters=None):
        monkeypatch.setenv("WA_A11Y_WAIT_S", str(seconds))
        if waiters is not None:
            monkeypatch.setenv("WA_A11Y_MAX_WAITERS", str(waiters))

    monkeypatch.setattr(jobs, "WAIT_POLL_S", 0.05)
    monkeypatch.setattr(jobs, "waiters", jobs._Waiters())
    return set_


def add_scan(status=ScanStatus.QUEUED, url="https://example.org/") -> int:
    with Session(get_engine()) as s:
        scan = Scan(url=url, level=Level.AA, engines=["axe"], profiles=["desktop"], status=status)
        s.add(scan)
        s.commit()
        s.refresh(scan)
        return scan.id


def finish_later(delay, status=ScanStatus.DONE, scan_id=None, error=None):

    def run():
        with Session(get_engine()) as s:
            scan = s.get(Scan, scan_id) if scan_id else s.exec(select(Scan)).all()[-1]
            scan.status, scan.error = status, error
            s.add(scan)
            s.commit()

    t = threading.Timer(delay, run)
    t.start()
    return t


def assert_no_refresh(html: str):
    low = html.lower()
    assert "<script" not in low and "http-equiv" not in low


def test_check_again_shows_results_as_soon_as_the_check_finishes(client, wait):
    wait(10)
    sid = add_scan()
    finish_later(0.3, scan_id=sid)
    start = time.monotonic()
    r = client.get(f"/scans/{sid}?wait=1")
    assert time.monotonic() - start < 3
    assert r.status_code == 303 and r.headers["location"] == f"/scans/{sid}"
    assert_no_refresh(r.text)
    done = client.get(r.headers["location"])
    # WCAG 2.2 SC 2.4.2: new state in the title
    assert "<title>Check" in done.text and "Finished" in done.text
    assert_no_refresh(done.text)


def test_start_the_check_waits_then_redirects_to_results(client, wait, monkeypatch):
    wait(10)
    monkeypatch.setattr(routes, "check_scan_url", lambda url: url.strip())
    token = re.search(r'name="csrf" value="([^"]+)"', client.get("/").text).group(1)
    finish_later(0.3)
    start = time.monotonic()
    r = client.post(
        "/scans",
        data={
            "csrf": token,
            "url": "https://example.org/",
            "level": "2.2-AA",
            "engines": ["axe"],
            "consent": "yes",
        },
    )
    assert time.monotonic() - start < 3
    assert r.status_code == 303
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    assert jobs.scan_status(sid) is ScanStatus.DONE


def test_timeout_falls_back_to_the_waiting_page_with_queue_place(client, wait):
    wait(1)
    sid = add_scan()
    start = time.monotonic()
    r = client.get(f"/scans/{sid}?wait=1")
    elapsed = time.monotonic() - start
    assert 0.9 <= elapsed < 3
    assert r.status_code == 200
    assert "Your check is in progress" in r.text
    assert "1st of 1 waiting" in r.text
    assert "waits up to 1 second for the check to finish" in r.text
    assert 'name="wait" value="1"' in r.text and "Check again" in r.text
    assert_no_refresh(r.text)


def test_error_redirects_to_the_error_page(client, wait):
    wait(10)
    sid = add_scan(status=ScanStatus.RUNNING)
    finish_later(0.2, ScanStatus.ERROR, sid, "The checking service is not available right now.")
    r = client.get(f"/scans/{sid}?wait=1")
    assert r.status_code == 303 and r.headers["location"] == f"/scans/{sid}"
    page = client.get(r.headers["location"]).text
    assert "The check could not finish" in page and "Could not finish" in page
    assert_no_refresh(page)


def test_plain_get_never_waits(client, wait):
    wait(60)
    sid = add_scan()
    start = time.monotonic()
    r = client.get(f"/scans/{sid}")
    assert time.monotonic() - start < 2
    assert r.status_code == 200 and "Your check is in progress" in r.text
    assert "waits up to 60 seconds" in r.text


def test_finished_scan_with_wait_redirects_at_once(client, wait):
    wait(60)
    sid = add_scan(status=ScanStatus.DONE)
    r = client.get(f"/scans/{sid}?wait=1")
    assert r.status_code == 303 and r.headers["location"] == f"/scans/{sid}"


def test_unknown_scan_with_wait_is_404_without_waiting(client, wait):
    wait(60)
    start = time.monotonic()
    assert client.get("/scans/999?wait=1").status_code == 404
    assert time.monotonic() - start < 2


def test_wait_zero_hides_the_hint_and_never_waits(client, wait):
    wait(0)
    sid = add_scan()
    r = client.get(f"/scans/{sid}?wait=1")
    assert r.status_code == 200 and "waits up to" not in r.text


def test_full_house_gets_the_waiting_page_immediately(client, wait):
    wait(60, waiters=1)
    sid = add_scan()
    assert jobs.waiters.try_enter()
    try:
        start = time.monotonic()
        r = client.get(f"/scans/{sid}?wait=1")
        assert time.monotonic() - start < 2
        assert r.status_code == 200 and "Your check is in progress" in r.text
        assert_no_refresh(r.text)
    finally:
        jobs.waiters.leave()


def test_concurrent_waiters_are_capped_and_slots_are_released(wait):
    wait(0.5, waiters=2)
    sid = add_scan()

    async def main():
        start = time.monotonic()
        results = await asyncio.gather(*(jobs.wait_until_finished(sid) for _ in range(4)))
        return results, time.monotonic() - start, jobs.waiters.active

    results, elapsed, active = asyncio.run(main())
    assert results == [False] * 4 and elapsed < 2
    assert active == 0


def test_cap_rejects_extra_waiters_while_two_wait(wait):
    wait(0.5, waiters=2)
    sid = add_scan()
    seen = []

    async def main():
        tasks = [asyncio.create_task(jobs.wait_until_finished(sid)) for _ in range(2)]
        await asyncio.sleep(0.1)
        seen.append(jobs.waiters.active)
        start = time.monotonic()
        assert await jobs.wait_until_finished(sid) is False
        seen.append(time.monotonic() - start)
        await asyncio.gather(*tasks)

    asyncio.run(main())
    assert seen[0] == 2 and seen[1] < 0.1


def test_client_disconnect_stops_waiting(wait):
    wait(60)
    sid = add_scan()

    async def gone():
        return True

    async def main():
        start = time.monotonic()
        assert await jobs.wait_until_finished(sid, gone) is False
        return time.monotonic() - start

    assert asyncio.run(main()) < 1 and jobs.waiters.active == 0


def test_cancelled_wait_releases_its_slot(wait):
    wait(60)
    sid = add_scan()

    async def main():
        task = asyncio.create_task(jobs.wait_until_finished(sid))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert jobs.waiters.active == 0


@pytest.mark.parametrize(
    "raw, seconds",
    [("60", 60), ("0", 0), ("-5", 0), ("500", 120), ("2.5", 2.5), ("soon", 60), ("nan", 60)],
)
def test_wait_seconds_is_clamped(monkeypatch, raw, seconds):
    monkeypatch.setenv("WA_A11Y_WAIT_S", raw)
    assert jobs.wait_seconds() == seconds


def test_wait_seconds_default(monkeypatch):
    monkeypatch.delenv("WA_A11Y_WAIT_S", raising=False)
    assert jobs.wait_seconds() == 60


@pytest.mark.parametrize("raw, n", [("8", 8), ("0", 1), ("-3", 1), ("1000", 64), ("x", 8)])
def test_max_waiters_is_clamped(monkeypatch, raw, n):
    monkeypatch.setenv("WA_A11Y_MAX_WAITERS", raw)
    assert jobs.max_waiters() == n


def test_one_account_cannot_take_every_waiting_slot(monkeypatch):
    monkeypatch.setenv("WA_A11Y_MAX_WAITERS", "8")
    monkeypatch.setenv("WA_A11Y_MAX_WAITERS_PER_USER", "2")
    w = jobs._Waiters()
    assert w.try_enter(1) and w.try_enter(1)
    assert not w.try_enter(1)
    assert w.try_enter(2)
    w.leave(1)
    assert w.try_enter(1)
    for who in (1, 1, 2):
        w.leave(who)
    assert w.active == 0 and w.per_user == {}
