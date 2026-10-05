# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlmodel import Session, select
from starlette.testclient import TestClient

import app.main as main
from app import jobs
from app.privacy import Authorization, NotAuthorized
from app.store.db import make_engine
from app.store.models import Engine, Finding, Level, Outcome, Scan, ScanStatus, Source

WEB = Path(__file__).parents[1]


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'wa.db'}"
    cfg = Config(str(WEB / "alembic.ini"))
    cfg.set_main_option("script_location", str(WEB / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    eng = make_engine(url)
    yield eng
    eng.dispose()


class FakeScanner:
    def __init__(self):
        self.response: dict = {}
        self.delay = 0.0
        self.requests: list[dict] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                fake.requests.append(
                    json.loads(self.rfile.read(int(self.headers["content-length"])))
                )
                time.sleep(fake.delay)
                body = json.dumps(fake.response).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def scanner(monkeypatch):
    fake = FakeScanner()
    monkeypatch.setenv("SCANNER_URL", fake.url)
    monkeypatch.setenv("WA_A11Y_SCAN_TIMEOUT_S", "5")
    yield fake
    fake.close()


DONE = {
    "status": "done",
    "toolVersions": {"axe-core": "4.13.0", "@siteimprove/alfa-test-utils": "0.84.2"},
    "blockedRequests": ["GET http://10.0.0.1/x.png — 10.0.0.1:80 resolves to a non-public address"],
    "findings": [
        {
            "engine": "axe",
            "outcome": "fail",
            "ruleId": "image-alt",
            "sc": ["1.1.1"],
            "wcagLevel": "A",
            "selector": "img",
            "html": "<img src=x>",
            "message": "Fix: add alt",
            "impact": "critical",
            "profiles": ["desktop"],
        },
        {
            "engine": "alfa",
            "outcome": "cantTell",
            "ruleId": "sia-r14",
            "sc": ["2.5.3", "4.1.2"],
            "wcagLevel": "A",
            "selector": "/html/body/button",
            "html": "<button>",
            "message": "",
            "impact": None,
            "profiles": ["desktop", "mobile-320"],
        },
    ],
}


def _queue(engine, n=1, url="https://example.org/"):
    with Session(engine) as s:
        return [
            jobs.enqueue(
                s,
                f"{url}{i}",
                Level.AA,
                ["axe", "alfa"],
                authorization=Authorization(True, "tester@example.com"),
            ).id
            for i in range(n)
        ]


def _scan(engine, scan_id) -> Scan:
    with Session(engine) as s:
        return s.get(Scan, scan_id)


def test_claim_is_fifo_and_marks_running(engine):
    ids = _queue(engine, 3)
    assert jobs.claim_next(engine) == ids[0]
    assert jobs.claim_next(engine) == ids[1]
    scan = _scan(engine, ids[0])
    assert scan.status is ScanStatus.RUNNING
    assert scan.started_at is not None
    jobs.claim_next(engine)
    assert jobs.claim_next(engine) is None


def test_concurrent_claims_never_double_claim(engine, monkeypatch):
    monkeypatch.setenv("WA_A11Y_MAX_QUEUED", "100")
    _queue(engine, 30)
    claimed: list[int] = []
    lock = threading.Lock()

    def worker():
        while (sid := jobs.claim_next(engine)) is not None:
            with lock:
                claimed.append(sid)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(claimed) == 30
    assert len(set(claimed)) == 30


def test_interrupted_scans_become_errors_not_done(engine):
    ids = _queue(engine, 2)
    jobs.claim_next(engine)
    assert jobs.recover_interrupted(engine) == 1
    assert _scan(engine, ids[0]).status is ScanStatus.ERROR
    assert "interrupted" in _scan(engine, ids[0]).error
    assert _scan(engine, ids[1]).status is ScanStatus.QUEUED


def test_queue_position_follows_claim_order(engine):
    ids = _queue(engine, 5)
    with Session(engine) as s:
        assert jobs.queue_position(s, s.get(Scan, ids[2])) == (3, 5)
        assert jobs.queue_position(s, s.get(Scan, ids[0])) == (1, 5)
    jobs.claim_next(engine)
    with Session(engine) as s:
        assert jobs.queue_position(s, s.get(Scan, ids[0])) is None
        assert jobs.queue_position(s, s.get(Scan, ids[2])) == (2, 4)
        same = s.get(Scan, ids[3]).created_at
        tied = s.get(Scan, ids[4])
        tied.created_at = same
        s.add(tied)
        s.commit()
        assert jobs.queue_position(s, s.get(Scan, ids[4])) == (4, 4)
    assert [jobs.claim_next(engine) for _ in range(4)] == ids[1:]


def test_successful_scan_stores_findings(engine, scanner):
    scanner.response = DONE
    [sid] = _queue(engine)
    jobs.claim_next(engine)
    jobs.run_scan(engine, sid)
    scan = _scan(engine, sid)
    assert scan.status is ScanStatus.DONE
    assert scan.finished_at is not None
    assert scan.tool_versions["axe-core"] == "4.13.0"
    assert scan.blocked_requests and "10.0.0.1" in scan.blocked_requests[0]
    assert scanner.requests[0] == {
        "url": "https://example.org/0",
        "level": "2.2-AA",
        "engines": ["axe", "alfa"],
        "profiles": ["desktop"],
        "authorization": {"privacy_consent": True, "authorized_by": "tester@example.com"},
    }
    with Session(engine) as s:
        found = {f.rule_id: f for f in s.exec(select(Finding).where(Finding.scan_id == sid))}
    assert found["image-alt"].outcome is Outcome.FAIL and found["image-alt"].engine is Engine.AXE
    assert found["image-alt"].impact == "critical"
    assert found["sia-r14"].outcome is Outcome.CANT_TELL and found["sia-r14"].impact is None
    assert found["sia-r14"].sc == "2.5.3,4.1.2"
    assert found["sia-r14"].profiles == ["desktop", "mobile-320"]
    assert len(found["image-alt"].fingerprint) == 32
    assert found["image-alt"].fingerprint == jobs.fingerprint(
        "https://example.org/0", "axe", "image-alt", "img"
    )


def test_scanner_reported_error_is_an_error(engine, scanner):
    scanner.response = {**DONE, "status": "error", "error": "desktop/alfa: boom"}
    [sid] = _queue(engine)
    jobs.claim_next(engine)
    jobs.run_scan(engine, sid)
    scan = _scan(engine, sid)
    assert scan.status is ScanStatus.ERROR
    assert "boom" in scan.error


def test_timeout_is_an_error_never_partial_done(engine, scanner, monkeypatch):
    monkeypatch.setenv("WA_A11Y_SCAN_TIMEOUT_S", "0.3")
    scanner.response, scanner.delay = DONE, 1.0
    [sid] = _queue(engine)
    jobs.claim_next(engine)
    jobs.run_scan(engine, sid)
    scan = _scan(engine, sid)
    assert scan.status is ScanStatus.ERROR
    assert "too long" in scan.error
    with Session(engine) as s:
        assert s.exec(select(Finding).where(Finding.scan_id == sid)).all() == []


def test_scanner_down_is_an_error(engine, monkeypatch):
    monkeypatch.setenv("SCANNER_URL", "http://127.0.0.1:9")
    [sid] = _queue(engine)
    jobs.claim_next(engine)
    jobs.run_scan(engine, sid)
    assert _scan(engine, sid).status is ScanStatus.ERROR
    assert "not available" in _scan(engine, sid).error


def test_runner_processes_queue_end_to_end(engine, scanner, monkeypatch):
    monkeypatch.setattr(jobs, "POLL_SECONDS", 0.05)
    scanner.response = DONE
    runner = jobs.Runner(engine, concurrency=2)
    runner.start()
    try:
        ids = _queue(engine, 3)
        deadline = time.time() + 10
        while time.time() < deadline and any(
            _scan(engine, i).status is not ScanStatus.DONE for i in ids
        ):
            time.sleep(0.05)
    finally:
        runner.stop()
    assert all(_scan(engine, i).status is ScanStatus.DONE for i in ids)


def test_app_lifespan_starts_and_stops_runner(monkeypatch):
    events = []

    class FakeRunner:
        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

    monkeypatch.setattr(main, "Runner", FakeRunner)
    monkeypatch.setenv("WA_A11Y_RUNNER", "1")
    with TestClient(main.app) as client:
        assert client.get("/healthz").text == "ok"
    assert events == ["start", "stop"]


def test_enqueue_refuses_without_authorization(engine):
    with Session(engine) as s:
        for auth in (None, Authorization(False, "x@example.com"), Authorization(True, "  ")):
            with pytest.raises(NotAuthorized):
                jobs.enqueue(s, "https://example.org/", Level.AA, ["axe"], authorization=auth)
        assert s.exec(select(Scan)).all() == []


def test_runner_refuses_an_unauthorized_scan_row(engine, scanner):
    scanner.response = DONE
    with Session(engine) as s:
        scan = Scan(url="https://example.org/", level=Level.AA, engines=["axe"])
        s.add(scan)
        s.commit()
        sid = scan.id
    jobs.claim_next(engine)
    jobs.run_scan(engine, sid)
    assert _scan(engine, sid).status is ScanStatus.ERROR
    assert "not authorized" in _scan(engine, sid).error
    assert scanner.requests == []


def test_detected_private_data_is_counted_not_stored(engine, scanner):
    mail = "jane.doe" + "@" + "dept.invalid"  # no personal-looking address in git (pii-scan)
    pii = {
        **DONE["findings"][0],
        "html": f"<p>SSN 123-45-6789, mail {mail}</p>",
        "selector": "p.x",
    }
    scanner.response = {**DONE, "findings": [pii]}
    [sid] = _queue(engine)
    jobs.claim_next(engine)
    jobs.run_scan(engine, sid)
    flags = _scan(engine, sid).pii_flags
    assert flags == {"US Social Security number": 1, "email address": 1}
    assert "123-45-6789" not in str(flags)


def _ingest(engine, scanner, findings: list) -> list[Finding]:
    scanner.response = {**DONE, "findings": findings}
    [sid] = _queue(engine)
    jobs.claim_next(engine)
    jobs.run_scan(engine, sid)
    assert _scan(engine, sid).status is ScanStatus.DONE
    with Session(engine) as s:
        return list(s.exec(select(Finding).where(Finding.scan_id == sid).order_by(Finding.id)))


def test_contract_findings_keep_source_and_engine(engine, scanner):
    axe, alfa = ({**f, "source": "automated"} for f in DONE["findings"])
    fastpass = {
        **axe,
        "engine": "accessibility-insights-fastpass",
        "ruleId": "focus-indicator",
        "sc": ["2.4.7"],
        "wcagLevel": "AA",
    }
    stored = _ingest(engine, scanner, [axe, alfa, fastpass])
    assert [(f.source, f.engine, f.outcome) for f in stored] == [
        (Source.AUTOMATED, Engine.AXE, Outcome.FAIL),
        (Source.AUTOMATED, Engine.ALFA, Outcome.CANT_TELL),
        (Source.AUTOMATED, Engine.FASTPASS, Outcome.FAIL),
    ]
    assert not any(f.advisory for f in stored)


def test_pre_contract_scanner_output_is_automated(engine, scanner):
    stored = _ingest(engine, scanner, DONE["findings"])
    assert {f.source for f in stored} == {Source.AUTOMATED}


def test_unmapped_checks_are_advisory_never_wcag_failures(engine, scanner):
    base = DONE["findings"][0]
    stored = _ingest(
        engine,
        scanner,
        [
            {**base, "ruleId": "no-sc", "sc": [], "wcagLevel": None},
            {**base, "ruleId": "bogus-sc", "sc": ["9.9.9", "4.1.1"], "wcagLevel": "A"},
            {**base, "ruleId": "no-level", "sc": ["1.1.1"], "wcagLevel": None},
            {**base, "ruleId": "odd-outcome", "outcome": "violation"},
        ],
    )
    by_rule = {f.rule_id: f for f in stored}
    for rule in ("no-sc", "bogus-sc", "no-level"):
        f = by_rule[rule]
        assert f.advisory and f.wcag_level is None, rule
        assert f.outcome is Outcome.CANT_TELL, f"{rule} became a WCAG failure"
    assert by_rule["bogus-sc"].sc is None
    # an outcome the contract does not know is a review item, never a failure
    assert by_rule["odd-outcome"].outcome is Outcome.CANT_TELL
    assert not by_rule["odd-outcome"].advisory


def test_results_the_scanner_must_not_supply_are_not_stored(engine, scanner):
    base = {**DONE["findings"][0], "source": "automated"}
    stored = _ingest(
        engine,
        scanner,
        [
            {**base, "ruleId": "kept"},
            {**base, "ruleId": "guided", "source": "guided"},
            {**base, "ruleId": "manual", "source": "manual"},
            {**base, "ruleId": "unknown-engine", "engine": "wave"},
            {**base, "ruleId": "no-engine", "engine": None},
            {**base, "ruleId": "passed", "outcome": "pass"},
            {**base, "ruleId": "n-a", "outcome": "notApplicable"},
            "not an object",
        ],
    )
    assert [f.rule_id for f in stored] == ["kept"]


def test_evidence_is_bounded_and_still_scanned_for_private_data(engine, scanner):
    mail = "jane.doe" + "@" + "dept.invalid"  # no personal-looking address in git (pii-scan)
    huge = {
        **DONE["findings"][0],
        "html": f"<p>{mail}</p>" + "x" * 50_000,
        "selector": "s" * 5_000,
        "message": "m" * 5_000,
        "ruleId": "r" * 1_000,
        "impact": "i" * 100,
        "profiles": [f"p{i}" for i in range(50)],
    }
    [f] = _ingest(engine, scanner, [huge])
    assert len(f.html_snippet) == 2000 and len(f.selector) == 500 and len(f.message) == 2000
    assert len(f.rule_id) == 200 and len(f.impact) == 20 and len(f.profiles) == 10
    assert _scan(engine, f.scan_id).pii_flags == {"email address": 1}


def test_scan_is_indexed_before_it_is_marked_done(engine, scanner, monkeypatch):
    # indexed while RUNNING (deletion refuses it), so a deleted check is never re-indexed
    seen = []
    monkeypatch.setattr(jobs, "_index", lambda session, scan: seen.append(scan.status))
    scanner.response = DONE
    [sid] = _queue(engine)
    jobs.claim_next(engine)
    jobs.run_scan(engine, sid)
    assert seen == [ScanStatus.RUNNING]
    assert _scan(engine, sid).status is ScanStatus.DONE
