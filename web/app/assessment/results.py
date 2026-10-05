# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

# Reviewer notes are scanned for private data with the finding evidence

import json
from functools import cache
from pathlib import Path

from sqlmodel import Session, select

from app.privacy import detect
from app.store.models import (
    AssessmentResult,
    Finding,
    Level,
    ReviewStatus,
    Scan,
    Source,
    utcnow,
)

CHECKLIST_ID = "wa-a11y-assessment"
CHECKLIST_PATH = Path(__file__).with_name("checklist.json")
NOTES_MAX = 2000
REVIEWER_MAX = 320


@cache
def checklist() -> dict:
    return json.loads(CHECKLIST_PATH.read_text(encoding="utf-8"))


def _item(item_id: str) -> dict:
    for item in checklist()["items"]:
        if item["id"] == item_id:
            return item
    raise ValueError(f"unknown Assessment checklist item: {item_id!r}")


def applicable(level: Level) -> list[dict]:
    levels = {"A", "AA", "AAA"} if level is Level.AAA else {"A", "AA"}
    return [item for item in checklist()["items"] if item["level"] in levels]


def saved(session: Session, scan_id: int) -> dict[str, AssessmentResult]:
    rows = session.exec(
        select(AssessmentResult).where(
            AssessmentResult.scan_id == scan_id,
            AssessmentResult.checklist_id == CHECKLIST_ID,
            AssessmentResult.checklist_version == int(checklist()["version"]),
        )
    )
    return {r.item_id: r for r in rows}


def progress(scan: Scan, results: dict[str, AssessmentResult]) -> tuple[int, int]:
    items = applicable(scan.level)
    return sum(item["id"] in results for item in items), len(items)


def progress_text(recorded: int, total: int) -> str:
    return f"{recorded} of {total} checks recorded"


def stored_text_flags(session: Session, scan_id: int) -> dict[str, int]:
    # Kinds/counts only, never values
    findings = session.exec(select(Finding).where(Finding.scan_id == scan_id))
    notes = session.exec(select(AssessmentResult.notes).where(AssessmentResult.scan_id == scan_id))
    return detect(
        *(t for f in findings for t in (f.html_snippet, f.message, f.selector)),
        *notes,
    )


def record(
    session: Session,
    scan: Scan,
    item_id: str,
    status: ReviewStatus,
    reviewer: str,
    notes: str = "",
    source: Source = Source.GUIDED,
) -> AssessmentResult:
    if source is Source.AUTOMATED:
        raise ValueError("Assessment results are guided or manual, never automated")
    reviewer = (reviewer or "").strip()[:REVIEWER_MAX]
    if not reviewer:
        raise ValueError("a reviewer is required")
    item = _item(item_id)
    version = int(checklist()["version"])
    result = session.exec(
        select(AssessmentResult).where(
            AssessmentResult.scan_id == scan.id,
            AssessmentResult.checklist_id == CHECKLIST_ID,
            AssessmentResult.checklist_version == version,
            AssessmentResult.item_id == item_id,
        )
    ).first() or AssessmentResult(
        scan_id=scan.id,
        checklist_id=CHECKLIST_ID,
        checklist_version=version,
        item_id=item_id,
        status=status,
        reviewer=reviewer,
    )
    result.source = source
    result.sc = ",".join(item["sc"]) or None
    result.advisory = bool(item["advisory"])
    result.status = ReviewStatus(status)
    result.reviewer = reviewer
    result.reviewed_at = utcnow()
    result.notes = (notes or "").strip()[:NOTES_MAX]
    session.add(result)
    session.flush()
    scan.pii_flags = stored_text_flags(session, scan.id)
    session.add(scan)
    session.commit()
    session.refresh(result)
    return result
