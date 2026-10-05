# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import asyncio
import hashlib
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import DateTime, bindparam, text
from sqlalchemy.engine import Engine as SAEngine
from sqlmodel import Session, func, select

from app.privacy import Authorization, NotAuthorized, detect
from app.store.db import get_engine
from app.store.models import Engine, Finding, Level, Outcome, Scan, ScanStatus, Source
from app.wcag import SC

log = logging.getLogger("wa_a11y.jobs")

POLL_SECONDS = 2.0


def _now() -> datetime:
    return datetime.now(UTC)


def scanner_url() -> str:
    return os.environ.get("SCANNER_URL", "http://scanner:3001").rstrip("/")


def scan_timeout() -> float:
    return float(os.environ.get("WA_A11Y_SCAN_TIMEOUT_S", "300"))


def fingerprint(url: str, engine: str, rule_id: str, selector: str) -> str:
    return hashlib.sha256(f"{url}\x1f{engine}\x1f{rule_id}\x1f{selector}".encode()).hexdigest()[:32]


class QueueFull(Exception):
    """Too many checks waiting; ask the user to try again later."""


def max_queued() -> int:
    return int(os.environ.get("WA_A11Y_MAX_QUEUED", "20"))


def pending_count(session: Session) -> int:
    return session.exec(
        select(func.count())
        .select_from(Scan)
        .where(Scan.status.in_([ScanStatus.QUEUED, ScanStatus.RUNNING]))
    ).one()


def queue_position(session: Session, scan: Scan) -> tuple[int, int] | None:
    if scan.status is not ScanStatus.QUEUED:
        return None
    queued = Scan.status == ScanStatus.QUEUED
    waiting = session.exec(select(func.count()).select_from(Scan).where(queued)).one()
    ahead = session.exec(
        select(func.count())
        .select_from(Scan)
        .where(
            queued,
            (Scan.created_at < scan.created_at)
            | ((Scan.created_at == scan.created_at) & (Scan.id < scan.id)),
        )
    ).one()
    return ahead + 1, waiting


def enqueue(
    session: Session,
    url: str,
    level: Level,
    engines: list[str],
    profiles: list[str] | None = None,
    requested_by: str | None = None,
    authorization: Authorization | None = None,
    created_by: int | None = None,
) -> Scan:
    # BEGIN IMMEDIATE: count-and-insert under the write lock, so the queue cap holds
    # Privacy rule: no scan without explicit consent and an authorizing user.
    if authorization is None:
        raise NotAuthorized("privacy consent and an authorizing user are required to scan")
    authorization.require()
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    if pending_count(session) >= max_queued():
        session.rollback()
        raise QueueFull
    scan = Scan(
        url=url,
        level=level,
        engines=engines,
        profiles=profiles or ["desktop"],
        requested_by=requested_by,
        created_by=created_by,
        privacy_consent=True,
        authorized_by=authorization.authorized_by.strip(),
        authorized_at=_now(),
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)
    return scan


_NOW = bindparam("now", type_=DateTime())


def claim_next(engine: SAEngine) -> int | None:
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        row = conn.execute(
            text(
                "UPDATE scan SET status = :running, started_at = :now "
                "WHERE id = (SELECT id FROM scan WHERE status = :queued "
                "ORDER BY created_at, id LIMIT 1) RETURNING id"
            ).bindparams(_NOW),
            {"running": ScanStatus.RUNNING.name, "queued": ScanStatus.QUEUED.name, "now": _now()},
        ).first()
        conn.exec_driver_sql("COMMIT")
    return row[0] if row else None


def recover_interrupted(engine: SAEngine) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE scan SET status = :error, finished_at = :now, "
                "error = 'The check was interrupted by a restart. Please run it again.' "
                "WHERE status = :running"
            ).bindparams(_NOW),
            {"error": ScanStatus.ERROR.name, "running": ScanStatus.RUNNING.name, "now": _now()},
        )
        return result.rowcount or 0


# WCAG 2.2 SC 3.2.5: no self-refreshing page; the request waits on the server instead

WAIT_DEFAULT_S = 60.0
WAIT_MAX_S = 120.0
WAIT_POLL_S = 0.5
WAITERS_DEFAULT = 8
WAITERS_MAX = 64


def _env_number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    if value != value:
        return default
    return max(low, min(value, high))


def wait_seconds() -> float:
    return _env_number("WA_A11Y_WAIT_S", WAIT_DEFAULT_S, 0.0, WAIT_MAX_S)


def max_waiters() -> int:
    return int(_env_number("WA_A11Y_MAX_WAITERS", WAITERS_DEFAULT, 1, WAITERS_MAX))


def max_waiters_per_user() -> int:
    """one account may hold only this many of the waiting slots."""
    return int(_env_number("WA_A11Y_MAX_WAITERS_PER_USER", 2, 1, WAITERS_MAX))


class _Waiters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.per_user: dict[object, int] = {}

    def try_enter(self, who: object = None) -> bool:
        with self._lock:
            if self.active >= max_waiters():
                return False
            if who is not None and self.per_user.get(who, 0) >= max_waiters_per_user():
                return False
            self.active += 1
            if who is not None:
                self.per_user[who] = self.per_user.get(who, 0) + 1
            return True

    def leave(self, who: object = None) -> None:
        with self._lock:
            self.active -= 1
            if who is not None:
                left = self.per_user.get(who, 1) - 1
                if left > 0:
                    self.per_user[who] = left
                else:
                    self.per_user.pop(who, None)


waiters = _Waiters()
FINISHED = (ScanStatus.DONE, ScanStatus.ERROR)


def scan_status(scan_id: int, engine: SAEngine | None = None) -> ScanStatus | None:
    with Session(engine or get_engine()) as session:
        scan = session.get(Scan, scan_id)
        return scan.status if scan else None


async def wait_until_finished(
    scan_id: int,
    disconnected: Callable[[], Awaitable[bool]] | None = None,
    engine: SAEngine | None = None,
    who: object = None,
) -> bool:
    timeout = wait_seconds()
    if timeout <= 0 or not waiters.try_enter(who):
        return False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            status = await asyncio.to_thread(scan_status, scan_id, engine)
            if status is None:
                return False
            if status in FINISHED:
                return True
            remaining = deadline - loop.time()
            if remaining <= 0 or (disconnected is not None and await disconnected()):
                return False
            await asyncio.sleep(min(WAIT_POLL_S, remaining))
    finally:
        waiters.leave(who)


def _call_scanner(scan: Scan) -> dict:
    body = json.dumps(
        {
            "url": scan.url,
            "level": scan.level.value,
            "engines": scan.engines,
            "profiles": scan.profiles,
            "authorization": {
                "privacy_consent": scan.privacy_consent,
                "authorized_by": scan.authorized_by,
            },
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310 — fixed internal service URL, not user input
        f"{scanner_url()}/scan", data=body, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=scan_timeout()) as resp:  # noqa: S310
        return json.load(resp)


_OUTCOMES = {"fail": Outcome.FAIL, "cantTell": Outcome.CANT_TELL}
# Never store per-element pass/notApplicable rows (data minimisation)
_NOT_STORED = {"pass", "notApplicable"}
_LEVELS = {"A", "AA", "AAA"}
# Screen-reader "not run" is stored as an error: it must never read as a pass
ARIA_NOT_RUN = "aria-tree-not-run"


def _outcome(engine: Engine, raw: object, rule_id: str) -> Outcome | None:
    if engine is Engine.ARIA_TREE:
        if rule_id == ARIA_NOT_RUN:
            return Outcome.ERROR
        if raw == "pass":
            return Outcome.PASS
    if raw in _NOT_STORED:
        return None
    return _OUTCOMES.get(raw, Outcome.CANT_TELL)


def _to_finding(scan: Scan, f: object) -> Finding | None:
    # Scanner output is untrusted: evidence is bounded again here
    if not isinstance(f, dict):
        return None
    if f.get("source", "automated") != "automated":
        return None  # guided/manual results come from a reviewer, never from the scanner
    try:
        engine = Engine(f.get("engine"))
    except ValueError:
        return None  # an unknown producer has no provenance we can stand behind
    rule_id = str(f.get("ruleId") or "")[:200]
    outcome = _outcome(engine, f.get("outcome"), rule_id)
    if outcome is None:
        return None
    sc = sorted({s for s in (f.get("sc") or []) if isinstance(s, str) and s in SC})
    level = f.get("wcagLevel") if sc and f.get("wcagLevel") in _LEVELS else None
    advisory = level is None
    if advisory and outcome is Outcome.FAIL:
        outcome = Outcome.CANT_TELL
    selector = str(f.get("selector") or "")[:500]
    impact = f.get("impact")
    return Finding(
        scan_id=scan.id,
        source=Source.AUTOMATED,
        engine=engine,
        outcome=outcome,
        advisory=advisory,
        rule_id=rule_id,
        sc=",".join(sc) or None,
        wcag_level=level,
        selector=selector,
        html_snippet=str(f.get("html") or "")[:2000],
        message=str(f.get("message") or "")[:2000],
        impact=str(impact)[:20] if impact else None,
        profiles=[str(p)[:40] for p in (f.get("profiles") or [])][:10],
        fingerprint=fingerprint(scan.url, engine.value, rule_id, selector),
    )


def _to_findings(scan: Scan, result: dict) -> list[Finding]:
    raw = result.get("findings") or []
    out = [f for f in (_to_finding(scan, r) for r in raw) if f is not None]
    if len(out) < len(raw):
        log.info("scan %s: %d scanner result(s) not stored", scan.id, len(raw) - len(out))
    return out


def _finish(session: Session, scan: Scan, status: ScanStatus, error: str | None = None) -> None:
    scan.status = status
    scan.error = error
    scan.finished_at = _now()
    session.add(scan)
    session.commit()


def run_scan(engine: SAEngine, scan_id: int) -> None:
    with Session(engine) as session:
        scan = session.get(Scan, scan_id)
        if scan is None:
            return
        try:
            Authorization(scan.privacy_consent, scan.authorized_by or "").require()
        except NotAuthorized:
            return _finish(
                session, scan, ScanStatus.ERROR, "This check was not authorized, so it was not run."
            )
        try:
            result = _call_scanner(scan)
        except TimeoutError:
            return _finish(
                session, scan, ScanStatus.ERROR, "The check took too long and was stopped."
            )
        except (urllib.error.URLError, OSError, ValueError) as err:
            log.warning("scanner call failed for scan %s: %s", scan_id, err)
            return _finish(
                session, scan, ScanStatus.ERROR, "The checking service is not available right now."
            )

        scan.tool_versions = {str(k): str(v) for k, v in (result.get("toolVersions") or {}).items()}
        scan.blocked_requests = [str(b)[:500] for b in (result.get("blockedRequests") or [])][:100]
        findings = _to_findings(scan, result)
        for finding in findings:
            session.add(finding)
        # Potential private data in captured content: kinds/counts only, never values
        scan.pii_flags = detect(
            *(t for f in findings for t in (f.html_snippet, f.message, f.selector))
        )
        if result.get("status") == "done":
            # Index before DONE: deleted checks must never be re-indexed
            session.add(scan)
            session.commit()
            _index(session, scan)
            _finish(session, scan, ScanStatus.DONE)
        else:
            _finish(
                session,
                scan,
                ScanStatus.ERROR,
                str(result.get("error") or "The check failed.")[:2000],
            )


def _index(session: Session, scan: Scan) -> None:
    if os.environ.get("WA_A11Y_RAG", "1") == "0":
        return
    try:
        from app import rag

        findings = list(session.exec(select(Finding).where(Finding.scan_id == scan.id)))
        rag.index_scan(scan, findings)
    except Exception:
        log.exception("RAG indexing failed for scan %s (reindex will repair)", scan.id)


def _retry_forgets(engine: SAEngine) -> None:
    try:
        from app import deletion

        deletion.retry_pending(engine)
    except Exception:
        log.exception("retrying RAG clean-up failed")


class Runner:
    def __init__(self, engine: SAEngine | None = None, concurrency: int | None = None) -> None:
        self.engine = engine or get_engine()
        n = concurrency or int(os.environ.get("WA_A11Y_RUNNER_CONCURRENCY", "1"))
        self.concurrency = max(1, min(n, 2))
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def _loop(self) -> None:
        while not self._stop.is_set():
            _retry_forgets(self.engine)
            try:
                scan_id = claim_next(self.engine)
            except Exception:
                log.exception("claim failed")
                scan_id = None
            if scan_id is None:
                self._stop.wait(POLL_SECONDS)
                continue
            run_scan(self.engine, scan_id)

    def _ensure_index(self) -> None:
        try:
            from sqlmodel import Session as S

            from app import rag

            with S(self.engine) as s:
                done = s.exec(
                    select(func.count()).select_from(Scan).where(Scan.status == ScanStatus.DONE)
                ).one()
            if done and rag.collection("findings").count() == 0:
                findings, guidance = rag.reindex(self.engine)
                log.warning(
                    "RAG index rebuilt: %d findings, %d guidance records", findings, guidance
                )
            elif rag.collection("guidance").count() == 0:
                rag.seed_guidance()
        except Exception:
            log.exception("RAG index check failed (run: python -m app.rag reindex)")

    def start(self) -> None:
        if os.environ.get("WA_A11Y_RAG", "1") != "0":
            threading.Thread(target=self._ensure_index, name="rag-index", daemon=True).start()
        recovered = recover_interrupted(self.engine)
        if recovered:
            log.warning("marked %d interrupted scan(s) as error", recovered)
        for i in range(self.concurrency):
            t = threading.Thread(target=self._loop, name=f"scan-runner-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout)


def runner_enabled() -> bool:
    return os.environ.get("WA_A11Y_RUNNER", "1") != "0"
