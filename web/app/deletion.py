# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import logging
import os
from enum import StrEnum

from sqlmodel import Session, delete, select

from app.store.models import Role, Scan, ScanDeletion, ScanStatus

log = logging.getLogger("wa_a11y.deletion")

PENDING = (ScanStatus.QUEUED, ScanStatus.RUNNING)


class Refusal(StrEnum):
    MISSING = "missing"
    FORBIDDEN = "forbidden"
    PENDING = "pending"


def may_delete(user, scan: Scan) -> bool:
    """Permission only (not state): creator or admin; legacy checks admin only."""
    if user is None or getattr(user, "id", None) is None:
        return False
    if user.role == Role.ADMIN:
        return True
    return scan.created_by is not None and scan.created_by == user.id


def refusal(user, scan: Scan | None) -> Refusal | None:
    if scan is None:
        return Refusal.MISSING
    if not may_delete(user, scan):
        return Refusal.FORBIDDEN
    if scan.status in PENDING:
        return Refusal.PENDING
    return None


def delete_scan(session: Session, user, scan_id: int) -> Refusal | None:
    # BEGIN IMMEDIATE: re-check under the write lock (delete vs runner race)
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    scan = session.get(Scan, scan_id)
    why = refusal(user, scan)
    if why is not None:
        session.rollback()
        return why
    result = session.exec(delete(Scan).where(Scan.id == scan_id, Scan.status.not_in(PENDING)))
    if result.rowcount != 1:
        session.rollback()
        return Refusal.PENDING
    record = ScanDeletion(scan_id=scan_id, deleted_by=user.email)
    session.add(record)
    session.commit()
    if _forget(scan_id):
        record.rag_cleared = True
        session.add(record)
        session.commit()
    return None


def _forget(scan_id: int) -> bool:
    # A failed clean-up is recorded and retried: page-derived snippets never stay in the index
    if os.environ.get("WA_A11Y_RAG", "1") == "0":
        return True
    try:
        from app import rag

        rag.forget_scan(scan_id)
        return True
    except Exception:
        log.exception("RAG cleanup failed for deleted scan %s (will retry)", scan_id)
        return False


def retry_pending(engine) -> int:
    done = 0
    with Session(engine) as session:
        pending = session.exec(
            select(ScanDeletion).where(ScanDeletion.rag_cleared == False)  # noqa: E712
        ).all()
        for record in pending:
            if _forget(record.scan_id):
                record.rag_cleared = True
                session.add(record)
                done += 1
        session.commit()
    return done


def deleted_by(session: Session, scan_id: int) -> str | None:
    row = session.exec(
        select(ScanDeletion).where(ScanDeletion.scan_id == scan_id).order_by(ScanDeletion.id.desc())
    ).first()
    return row.deleted_by if row else None
