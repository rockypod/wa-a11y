# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Level(StrEnum):
    AA = "2.2-AA"
    AAA = "2.2-AAA"


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class Engine(StrEnum):
    AXE = "axe"
    ALFA = "alfa"
    FASTPASS = "accessibility-insights-fastpass"
    ARIA_TREE = "aria-tree"


class Source(StrEnum):
    AUTOMATED = "automated"
    GUIDED = "guided"
    MANUAL = "manual"


class Outcome(StrEnum):
    FAIL = "fail"
    CANT_TELL = "cantTell"
    PASS = "pass"  # noqa: S105 — scan outcome, not a password
    ERROR = "error"  # engine/tool failure — never counted as a pass


class Scan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(index=True)
    level: Level
    engines: list[str] = Field(sa_column=Column(JSON, nullable=False))
    profiles: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: ScanStatus = Field(default=ScanStatus.QUEUED, index=True)
    tool_versions: dict[str, str] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    blocked_requests: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False, server_default="[]")
    )
    requested_by: str | None = None
    created_by: int | None = Field(
        default=None, foreign_key="user.id", index=True, ondelete="SET NULL"
    )
    error: str | None = None
    # Privacy rule: consent before scanning + provenance stamp
    privacy_consent: bool = Field(default=False, sa_column_kwargs={"server_default": "0"})
    authorized_by: str | None = None
    authorized_at: datetime | None = None
    # Mandatory human verification: automated results are a pre-check only
    automated_precheck: bool = Field(default=True, sa_column_kwargs={"server_default": "1"})
    verified_by: str | None = None
    verification_date: datetime | None = None
    # Potential private data detected in captured content: {kind: count} — never the values
    pii_flags: dict[str, int] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False, server_default="{}")
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Finding(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True, ondelete="CASCADE")
    source: Source = Field(
        default=Source.AUTOMATED, sa_column_kwargs={"server_default": "AUTOMATED"}
    )
    engine: Engine
    outcome: Outcome
    advisory: bool = Field(default=False, sa_column_kwargs={"server_default": "0"})
    rule_id: str
    sc: str | None = Field(default=None, index=True)
    wcag_level: str | None = None
    selector: str = ""
    html_snippet: str = ""  # untrusted page content: always render escaped
    message: str = ""
    impact: str | None = None
    profiles: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    fingerprint: str = Field(index=True)


class ReviewStatus(StrEnum):
    PASS = "pass"  # noqa: S105 — review outcome, not a password
    FAIL = "fail"
    NEEDS_REVIEW = "needs-review"
    NOT_APPLICABLE = "not-applicable"


class AssessmentResult(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("scan_id", "checklist_id", "checklist_version", "item_id"),)

    id: int | None = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True, ondelete="CASCADE")
    source: Source = Field(default=Source.GUIDED)
    checklist_id: str
    checklist_version: int
    item_id: str
    sc: str | None = None
    advisory: bool = False
    status: ReviewStatus
    reviewer: str
    reviewed_at: datetime = Field(default_factory=utcnow)
    notes: str = ""


class Prompt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True, ondelete="CASCADE")
    finding_id: int | None = Field(default=None, foreign_key="finding.id", ondelete="CASCADE")
    text: str
    created_at: datetime = Field(default_factory=utcnow)


class UrlStatus(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("url", "sc"),)

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(index=True)
    sc: str
    latest_outcome: Outcome
    last_scan_id: int = Field(foreign_key="scan.id", ondelete="CASCADE")


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str = ""
    password_hash: str
    role: Role = Field(default=Role.USER)
    is_active: bool = True
    failed_logins: int = 0
    locked_until: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None


class AuthSession(SQLModel, table=True):
    # Only the token's SHA-256 is stored: a database leak must not hand out live sessions
    id: int | None = Field(default=None, primary_key=True)
    token_hash: str = Field(unique=True, index=True)
    user_id: int = Field(foreign_key="user.id", index=True, ondelete="CASCADE")
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime


class PrivateDataGrant(SQLModel, table=True):
    # Insert-only audit log: kinds/counts flagged, never the values
    id: int | None = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True, ondelete="CASCADE")
    granted_by: str
    granted_at: datetime = Field(default_factory=utcnow)
    flags: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class ScanDeletion(SQLModel, table=True):
    # Insert-only audit log: never the address or results; no FK, so it outlives the cascade
    id: int | None = Field(default=None, primary_key=True)
    scan_id: int = Field(index=True)
    deleted_by: str
    deleted_at: datetime = Field(default_factory=utcnow)
    # False until the RAG index no longer holds the check; the runner retries.
    rag_cleared: bool = Field(default=False, sa_column_kwargs={"server_default": "0"}, index=True)
